package com.ganfeng.rs.extraction;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ganfeng.rs.common.BizException;
import com.ganfeng.rs.imagery.Imagery;
import com.ganfeng.rs.imagery.ImageryService;
import com.ganfeng.rs.project.Project;
import com.ganfeng.rs.project.ProjectService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestTemplate;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * 在线提取服务（真实解译链路）
 *
 * 流程：
 *   submit() → 调 inference /api/v1/inference/submit 提交异步任务
 *            → inference 后台算完回调 /api/callback/task-complete
 *            → complete() 把结果落库（extractions 表）
 *
 * 已移除：原 demo 的「按参数做种子的确定性模拟」——同一组参数永远出同一结果，
 * 那不是解译，只是造数据。
 */
@Service
public class ExtractionService {

    private static final Set<String> CLASS_TYPES = Set.of(
            "VEGETATION", "WATER", "BARE", "PIT", "DUMP", "TAILINGS", "ROAD");

    /** 可用于解译的卫星/数据源标识（与 inference classify.BANDS 表对应） */
    private static final Set<String> SATELLITES = Set.of(
            "SENTINEL2", "LANDSAT9", "GF2", "GF7", "UPLOAD");

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final ExtractionRepository repo;
    private final ImageryService imageryService;
    private final ProjectService projectService;
    private final RestTemplate rest;

    @Value("${INFERENCE_BASE_URL:http://localhost:8010}")
    private String inferenceBaseUrl;

    @Value("${JAVA_CALLBACK_URL:http://localhost:8080/api/callback/task-complete}")
    private String callbackUrl;

    public ExtractionService(ExtractionRepository repo, ImageryService imageryService,
                             ProjectService projectService) {
        this.repo = repo;
        this.imageryService = imageryService;
        this.projectService = projectService;
        // 超时用 SimpleClientHttpRequestFactory 设置（RestTemplate 的
        // setConnectTimeout(Duration) 是 Spring 6.1+ 才有的重载，此处用通用写法）
        var factory = new org.springframework.http.client.SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(10_000);
        factory.setReadTimeout(60_000);
        this.rest = new RestTemplate(factory);
    }

    /**
     * 解析解译算法用的卫星标识。
     *
     * imagery.source=UPLOAD 是用户上传的高分影像，其波段排布由「数据源」决定
     * （GF-2 四波段 / GF-7 等），而不是 source 本身。extract() 入参可显式指定
     * 算法卫星，不指定时回退到 imagery.source。
     */
    private String resolveSatellite(Imagery img, String algoSatellite) {
        if (algoSatellite != null && !algoSatellite.isBlank()) {
            String s = algoSatellite.toUpperCase(java.util.Locale.ROOT);
            if (SATELLITES.contains(s)) {
                return s;
            }
            throw BizException.badRequest("不支持的解译数据源: " + algoSatellite);
        }
        // 未指定：UPLOAD 走 GF2 波段映射（商业高分影像多为四波段）
        String src = img.getSource();
        if ("UPLOAD".equals(src)) {
            return "GF2";
        }
        String s = src.toUpperCase(java.util.Locale.ROOT);
        if (!SATELLITES.contains(s)) {
            throw BizException.badRequest("该影像暂不支持解译：" + img.getName());
        }
        return s;
    }

    /**
     * 列表：**按项目成员过滤**，避免非成员看到他人项目的解译结果。
     * projectId 为空时返回当前用户全部可见项目的记录。
     */
    public List<Extraction> list(Long projectId, String username, boolean isAdmin) {
        var visible = projectService.listForUser(username, isAdmin).stream()
                .map(Project::getId).toList();
        if (visible.isEmpty()) {
            return List.of();
        }
        if (projectId != null) {
            projectService.requireAccess(projectId, username, isAdmin);
        }
        return repo.findAll().stream()
                .filter(e -> visible.contains(e.getProjectId()))
                .filter(e -> projectId == null || e.getProjectId().equals(projectId))
                // 软删除的记录不进业务列表（进回收站）
                .filter(e -> !Boolean.TRUE.equals(e.getDeleted()))
                .sorted(java.util.Comparator.comparing(Extraction::getCreatedAt).reversed())
                .toList();
    }

    /** 仅按 id 读取（内部/已鉴权场景使用，不做成员校验） */
    public Extraction get(long id) {
        return repo.findById(id).orElseThrow(() -> BizException.notFound("提取记录不存在: " + id));
    }

    /** 读取单条并校验项目访问权 */
    public Extraction get(long id, String username, boolean isAdmin) {
        Extraction e = repo.findById(id)
                .orElseThrow(() -> BizException.notFound("提取记录不存在: " + id));
        projectService.requireAccess(e.getProjectId(), username, isAdmin);
        return e;
    }

    /**
     * 提交真实解译任务：选影像 + 圈 AOI + 选地物类型 → inference 异步计算
     *
     * @return inference 返回的 taskId（后续回调据此落库）
     */
    @Transactional
    public String submit(Long projectId, Long imageryId, String name, String classType,
                         List<List<Double>> aoi, String createdBy, String algoSatellite) {
        if (!CLASS_TYPES.contains(classType)) {
            throw BizException.badRequest("非法提取类型: " + classType);
        }
        if (aoi == null || aoi.size() < 3) {
            throw BizException.badRequest("AOI 至少需要 3 个顶点");
        }
        Imagery img = imageryService.get(imageryId);
        String satellite = resolveSatellite(img, algoSatellite);
        String path = imageryService.resolvePath(img);

        Map<String, Object> body = new HashMap<>();
        body.put("imagePath", path);
        body.put("satellite", satellite);
        body.put("classType", classType);
        body.put("algoType", "INDEX");
        body.put("aoi", aoi);
        // 上下文透传：inference 计算完成时原样回传，否则回调拿不到
        // projectId / imageryId，落库会变成 0 导致后续按项目过滤查不到结果
        body.put("projectId", projectId);
        body.put("imageryId", imageryId);
        body.put("name", name);
        body.put("acquisitionDate", img.getAcquisitionDate() == null ? null : img.getAcquisitionDate().toString());
        // AOI 随请求下发，回调时带回并落库 —— 时序匹配的依据
        body.put("aoi", aoi);
        body.put("callbackUrl", callbackUrl);

        try {
            String resp = rest.postForObject(inferenceBaseUrl + "/api/v1/inference/submit",
                    body, String.class);
            Map<?, ?> m = MAPPER.readValue(resp, Map.class);
            Object taskId = m.get("taskId");
            if (taskId == null) {
                throw BizException.badRequest("解译服务未返回任务号");
            }
            return taskId.toString();
        } catch (BizException e) {
            throw e;
        } catch (Exception e) {
            throw new BizException(502, "解译服务调用失败：" + e.getMessage());
        }
    }

    /**
     * 提交「在线 Sentinel-2 直接解译」任务（遥感提取页专用）
     *
     * 与 submit() 的区别：submit 要求先有本地影像（imageryId → filePath），
     * 本方法不需要本地影像 —— inference 用 AWS Earth Search STAC 在线拉景、
     * 按 AOI 剪切、算指数、矢量化，算完同样回调落库。
     *
     * @param startDate / endDate 影像日期范围
     * @return inference 返回的 taskId
     */
    public String submitOnline(Long projectId, String name, String classType,
                               List<List<Double>> aoi, String startDate, String endDate,
                               double maxCloud, Double threshold, int minAreaPx,
                               String createdBy) {
        if (aoi == null || aoi.size() < 3) {
            throw BizException.badRequest("AOI 至少需要 3 个顶点");
        }

        Map<String, Object> body = new HashMap<>();
        body.put("aoi", aoi);
        body.put("startDate", startDate);
        body.put("endDate", endDate);
        body.put("classType", classType);
        body.put("maxCloud", maxCloud);
        body.put("minAreaPx", minAreaPx);
        if (threshold != null) {
            body.put("threshold", threshold);
        }
        // 上下文透传：回调时带回，落库到正确项目
        body.put("projectId", projectId);
        body.put("name", name);
        body.put("callbackUrl", callbackUrl);

        try {
            String resp = rest.postForObject(
                    inferenceBaseUrl + "/api/v1/sentinel/extract-async", body, String.class);
            Map<?, ?> m = MAPPER.readValue(resp, Map.class);
            Object taskId = m.get("taskId");
            if (taskId == null) {
                throw BizException.badRequest("解译服务未返回任务号");
            }
            return taskId.toString();
        } catch (BizException e) {
            throw e;
        } catch (Exception e) {
            throw new BizException(502, "解译服务调用失败：" + e.getMessage());
        }
    }

    /**
     * 直接保存前端已算好的解译结果（遥感提取页专用）
     *
     * 遥感提取页走 /sentinel/extract 同步拿到完整结果（features + 覆盖率），
     * 保存时不再让 inference 重算，直接把结果落库。这样：
     *  - 提取预览即时（同步返回），体验好
     *  - 保存后进 extractions 表 → 时序播放 / 变化分析 / 权限 全生效
     *
     * @param features 矢量化多边形（List<List<List<Double>>> 外环坐标）
     */
    @Transactional
    public Extraction save(Long projectId, String name, String classType,
                           List<List<List<Double>>> features, String aoiJson,
                           double coveragePct, double aoiAreaHa, String acquisitionDate,
                           String satellite, String createdBy) {
        if (aoiJson == null || aoiJson.isBlank()) {
            throw BizException.badRequest("AOI 不能为空");
        }
        double extractHa = aoiAreaHa * coveragePct / 100.0;

        LocalDate acq = null;
        if (acquisitionDate != null && !acquisitionDate.isBlank()) {
            try {
                acq = LocalDate.parse(acquisitionDate.substring(0, 10));
            } catch (Exception ignored) {
                acq = null;
            }
        }

        Extraction e = new Extraction();
        e.setTaskId("local-" + System.currentTimeMillis());
        e.setProjectId(projectId);
        e.setImageryId(null);   // 在线方案无本地影像
        e.setName(name == null || name.isBlank()
                ? "提取-" + classType + "-" + acq : name);
        e.setClassType(classType);
        e.setSatellite(satellite == null || satellite.isBlank() ? "SENTINEL2" : satellite);
        e.setYear(acq == null ? LocalDate.now().getYear() : acq.getYear());
        e.setAcquisitionDate(acq);
        e.setFeaturesJson(toJson(features == null ? new ArrayList<>() : features));
        e.setAoiJson(aoiJson);
        e.setAoiSignature(aoiSignature(aoiJson));
        e.setAoiAreaHa(round2(aoiAreaHa));
        e.setExtractAreaHa(round2(extractHa));
        e.setCoveragePct(round2(coveragePct));
        e.setCreatedBy(createdBy);
        e.setCreatedAt(LocalDateTime.now());
        return repo.save(e);
    }

    /**
     * 接收 inference 回调结果并落库
     * 幂等：同一 taskId 重复回调只生效一次
     */
    @Transactional
    public void complete(String taskId, Long projectId, Long imageryId, String classType,
                         List<List<List<Double>>> features, int pixelCount,
                         double extractAreaHa, double aoiAreaHa, double coveragePct,
                         String name, String satellite, LocalDate acquisitionDate,
                         String aoiJson) {
        List<Extraction> existing = repo.findByTaskId(taskId);
        if (!existing.isEmpty()) {
            return; // 幂等：已落过库
        }
        double pct = coveragePct > 0 ? coveragePct
                : (aoiAreaHa > 0 ? extractAreaHa / aoiAreaHa * 100.0 : 0.0);

        Extraction e = new Extraction();
        e.setTaskId(taskId);
        e.setProjectId(projectId == null ? 0L : projectId);
        // 在线 Sentinel-2 方案无 imageryId（回调传 0），落库转 null 表示「非本地影像」
        e.setImageryId(imageryId != null && imageryId > 0 ? imageryId : null);
        e.setName(name == null || name.isBlank()
                ? "提取-" + classType + "-" + System.currentTimeMillis() : name);
        e.setClassType(classType);
        e.setSatellite(satellite == null || satellite.isBlank() ? "SENTINEL2" : satellite);
        e.setYear(acquisitionDate == null ? 2026 : acquisitionDate.getYear());
        e.setAcquisitionDate(acquisitionDate);
        e.setFeaturesJson(toJson(features == null ? new ArrayList<>() : features));
        // 记录 AOI 与其指纹：时序播放靠 aoiSignature 匹配「同一 AOI 的不同期结果」
        e.setAoiJson(aoiJson);
        e.setAoiSignature(aoiSignature(aoiJson));
        e.setPixelCount(pixelCount);
        e.setAoiAreaHa(round2(aoiAreaHa));
        e.setExtractAreaHa(round2(extractAreaHa));
        e.setCoveragePct(round2(pct));
        e.setCreatedAt(LocalDateTime.now());
        repo.save(e);
    }

    /**
     * 删除到回收站（软删除）。
     *
     * 为什么不物理删除：演示现场误删一条解译记录就少了历史期次，
     * 时序/报告会立刻缺数据且无法恢复。软删除后可从回收站还原。
     */
    @Transactional
    public void delete(long id, String username) {
        Extraction e = get(id);
        e.setDeleted(true);
        e.setDeletedAt(LocalDateTime.now());
        e.setDeletedBy(username);
        repo.save(e);
    }

    /** 回收站列表：已删除的记录（按删除时间倒序） */
    public List<Extraction> trash(Long projectId, String username, boolean isAdmin) {
        var visible = projectService.listForUser(username, isAdmin).stream()
                .map(Project::getId).toList();
        return repo.findAll().stream()
                .filter(e -> Boolean.TRUE.equals(e.getDeleted()))
                .filter(e -> visible.contains(e.getProjectId()))
                .filter(e -> projectId == null || e.getProjectId().equals(projectId))
                .sorted(java.util.Comparator.comparing(
                        (Extraction x) -> x.getDeletedAt() == null ? x.getCreatedAt() : x.getDeletedAt()).reversed())
                .toList();
    }

    /** 从回收站还原 */
    @Transactional
    public Extraction restore(long id) {
        Extraction e = get(id);
        e.setDeleted(false);
        e.setDeletedAt(null);
        e.setDeletedBy(null);
        return repo.save(e);
    }

    /** 彻底删除（仅回收站内记录可调用，不可恢复） */
    @Transactional
    public void purge(long id) {
        Extraction e = get(id);
        if (!Boolean.TRUE.equals(e.getDeleted())) {
            throw BizException.badRequest("只能彻底删除回收站内的记录，请先删除到回收站");
        }
        repo.deleteById(id);
    }

    /** 统计某个影像关联的解译记录数（删影像前提示，避免留下孤儿数据） */
    public long countByImagery(Long imageryId) {
        if (imageryId == null) return 0;
        return repo.findAll().stream()
                .filter(e -> !Boolean.TRUE.equals(e.getDeleted()))
                .filter(e -> imageryId.equals(e.getImageryId()))
                .count();
    }

    /** 影像删除时级联把关联解译记录放进回收站 */
    @Transactional
    public int trashByImagery(Long imageryId, String username) {
        if (imageryId == null) return 0;
        int n = 0;
        for (Extraction e : repo.findAll()) {
            if (Boolean.TRUE.equals(e.getDeleted())) continue;
            if (!imageryId.equals(e.getImageryId())) continue;
            e.setDeleted(true);
            e.setDeletedAt(LocalDateTime.now());
            e.setDeletedBy(username);
            repo.save(e);
            n++;
        }
        return n;
    }

    private static String toJson(Object o) {
        try {
            return MAPPER.writeValueAsString(o);
        } catch (Exception e) {
            throw new IllegalStateException("几何序列化失败", e);
        }
    }

    /** 供控制器把 JSON 几何还原给前端 */
    public static <T> T fromJson(String json, TypeReference<T> type) {
        try {
            return MAPPER.readValue(json, type);
        } catch (Exception e) {
            throw new IllegalStateException("几何反序列化失败", e);
        }
    }

    /**
     * AOI 指纹：把顶点归一化后取哈希，用于识别「同一 AOI 的不同期结果」。
     *
     * 三个坑（均为实测踩到）：
     * 1. **浮点尾数**：前端算出的 26.31 经 JSON 往返可能是 26.310000000000002，
     *    不先四舍五入会与另一期的 26.31 得到不同哈希。
     * 2. **闭合环重复点**：GeoJSON 环首尾点相同（闭合），该点因起点不同而在
     *    排序后落在不同位置 —— 必须先去掉重复点，否则同一区域哈希不同。
     * 3. **顶点顺序/起点**：同一区域可能从不同顶点起圈，需排序消除。
     *
     * 做法：四舍五入 → 去重（Set） → 排序 → 哈希。
     * 精度取 5 位小数（约 1.1m）：消除浮点噪音，又不会因人手重圈的
     * 十几米偏差而匹配不上。
     */
    public static String aoiSignature(String aoiJson) {
        if (aoiJson == null || aoiJson.isBlank()) {
            return null;
        }
        try {
            List<List<Double>> ring = MAPPER.readValue(aoiJson, new TypeReference<>() {});
            if (ring == null || ring.size() < 3) {
                return null;
            }
            // 用 Set 天然消除闭合环的重复点
            java.util.Set<String> unique = new java.util.TreeSet<>();
            for (List<Double> p : ring) {
                if (p == null || p.size() < 2) {
                    continue;
                }
                double lng = BigDecimal.valueOf(p.get(0)).setScale(5, RoundingMode.HALF_UP).doubleValue();
                double lat = BigDecimal.valueOf(p.get(1)).setScale(5, RoundingMode.HALF_UP).doubleValue();
                unique.add(String.format("%.5f,%.5f", lng, lat));
            }
            if (unique.size() < 3) {
                return null;
            }
            return String.valueOf(unique.hashCode());
        } catch (Exception e) {
            return null;
        }
    }

    private static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}