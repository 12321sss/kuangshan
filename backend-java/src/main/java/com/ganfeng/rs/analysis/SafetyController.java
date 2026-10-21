package com.ganfeng.rs.analysis;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ganfeng.rs.audit.AuditLogService;
import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.PermissionGuard;
import com.ganfeng.rs.extraction.Extraction;
import com.ganfeng.rs.extraction.ExtractionService;
import com.ganfeng.rs.project.Project;
import com.ganfeng.rs.project.ProjectService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.http.MediaType;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * 开采安全风险评估控制器
 *
 * 职责边界：本类只做「数据汇总 + 转发」，不做算法。
 * 真正的风险模型（几何并集、越界裁剪、栅格加权、热点提取）在 inference/risk.py，
 * 因为那些计算依赖 shapely / rasterio / numpy，Java 侧实现代价过高。
 *
 * 这里负责三件事：
 * 1. 从数据库取项目边界与解译几何（含去重口径：同区域同类取最新一次）
 * 2. 计算扩张速率等时序趋势指标（Java 侧已有去重逻辑，直接复用）
 * 3. 调用 inference 的风险接口并把结果原样返回（含口径红线声明）
 */
@RestController
@RequestMapping("/api/analysis")
public class SafetyController {

    /** 视为"扰动类"的地物类型：并集去重时只合并这些 */
    private static final List<String> DISTURBED_TYPES =
            List.of("PIT", "DUMP", "TAILINGS", "BARE", "ROAD");

    private static final org.slf4j.Logger logger =
            org.slf4j.LoggerFactory.getLogger(SafetyController.class);

    private final ExtractionService extractionService;
    private final ProjectService projectService;
    private final PermissionGuard guard;
    private final AuditLogService auditLogService;
    private final com.ganfeng.rs.boundary.AoiBoundaryController boundaryController;
    private final RestTemplate rest;
    private final ObjectMapper mapper = new ObjectMapper();

    @Value("${INFERENCE_BASE_URL:http://localhost:8010}")
    private String inferenceBaseUrl;

    public SafetyController(ExtractionService extractionService,
                            ProjectService projectService,
                            PermissionGuard guard,
                            AuditLogService auditLogService,
                            com.ganfeng.rs.boundary.AoiBoundaryController boundaryController,
                            RestTemplateBuilder builder) {
        this.extractionService = extractionService;
        this.projectService = projectService;
        this.guard = guard;
        this.auditLogService = auditLogService;
        this.boundaryController = boundaryController;
        // 风险计算含 DEM 下载与栅格运算，首次可能较慢，超时给足
        this.rest = builder
                .setConnectTimeout(Duration.ofSeconds(10))
                .setReadTimeout(Duration.ofSeconds(180))
                .build();
    }

    /**
     * 开采安全风险评估
     *
     * @param projectId 项目（缺省则取当前用户可见的全部）
     */
    @PostMapping("/safety-evaluate")
    public ApiResponse<Map<String, Object>> safetyEvaluate(
            @RequestParam(required = false) Long projectId,
            @RequestParam(defaultValue = "true") boolean withGrid,
            @RequestParam(defaultValue = "false") boolean withSlope,
            Authentication auth) {

        boolean isAdmin = guard.roleCodesOf(auth).contains("ADMIN");
        List<Extraction> all = extractionService.list(projectId, auth.getName(), isAdmin);

        // ---- 1. 项目边界 ----
        List<List<Double>> permit = new ArrayList<>();
        List<List<Double>> disturbance = new ArrayList<>();
        String projectName = "未指定项目";
        String permitSource = "none";
        if (projectId != null) {
            Project p = projectService.get(projectId);
            projectService.requireAccess(projectId, auth.getName(), isAdmin);
            projectName = p.getName();
            JsonNode boundary = parseJson(p.getBoundaryJson());
            disturbance = ringOf(boundary, "disturbance");

            // 优先级：客户导入的 SHP 边界（aoi_boundary 表）> 项目上手圈的 boundaryJson
            // 理由：导入的是登记数据（有坐标系、可追溯来源），手圈的是演示期临时勾的
            permit = boundaryController.permitRing(projectId);
            if (!permit.isEmpty()) {
                permitSource = "aoi_boundary";
            } else {
                permit = ringOf(boundary, "mining");
                if (!permit.isEmpty()) permitSource = "project_json";
            }
        }

        // ---- 2. 解译几何：同类型同 AOI 只取最新一次 ----
        Map<String, Extraction> latest = dedupLatest(all);
        if (latest.isEmpty()) {
            Map<String, Object> empty = new LinkedHashMap<>();
            empty.put("available", false);
            empty.put("message", "该项目还没有解译记录，无法做安全评估。请先在遥感提取页圈选并保存解译结果。");
            return ApiResponse.ok(empty);
        }

        // 分析范围口径：**矿权范围**才是"分析区"，扰动边界是被监测对象而非分析范围。
        // 若拿扰动边界当分析区，会出现"各类地物面积之和远超分析区"的假象
        // （因为解译是在更大范围上做的）。没有矿权边界时依次退化。
        List<List<Double>> aoi = !permit.isEmpty() ? permit
                : (!disturbance.isEmpty() ? disturbance : bboxOf(latest.values()));
        if (aoi.size() < 3) {
            Map<String, Object> empty = new LinkedHashMap<>();
            empty.put("available", false);
            empty.put("message", "无法确定分析范围，请在项目设置里登记矿权或扰动边界");
            return ApiResponse.ok(empty);
        }

        // ---- 3. 组装 classes（GeoJSON Feature 列表）----
        Map<String, List<Map<String, Object>>> byClass = new LinkedHashMap<>();
        for (Extraction e : latest.values()) {
            List<Map<String, Object>> features = toGeoJsonFeatures(e);
            if (!features.isEmpty()) {
                byClass.computeIfAbsent(e.getClassType(), k -> new ArrayList<>()).addAll(features);
            }
        }
        List<Map<String, Object>> classesPayload = new ArrayList<>();
        byClass.forEach((ct, feats) -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("classType", ct);
            m.put("features", feats);
            classesPayload.add(m);
        });

        // ---- 4. 时序趋势（D1 扩张速率）----
        Map<String, Object> trend = buildTrend(all);

        // ---- 4.5 RSEI 生态指数（生态维度输入；失败不阻塞整体评估）----
        // 日期范围由最新解译记录的拍摄日期往前推一年推导，避免前端额外传参。
        // RSEI 需拉 6 个波段（含 B12），首次约 1-3 分钟，之后有 tile 缓存。
        Map<String, Object> rseiStats = null;
        try {
            String latestDate = latest.values().stream()
                    .map(Extraction::getAcquisitionDate)
                    .filter(java.util.Objects::nonNull)
                    .max(java.util.Comparator.naturalOrder())
                    .map(java.time.LocalDate::toString)
                    .orElse(java.time.LocalDate.now().toString());
            String start = java.time.LocalDate.parse(latestDate).minusYears(1).toString();

            Map<String, Object> rq = new LinkedHashMap<>();
            rq.put("aoi", aoi);
            rq.put("start_date", start);
            rq.put("end_date", latestDate);
            rq.put("max_cloud", 40);
            rq.put("with_image", false);

            @SuppressWarnings("unchecked")
            Map<String, Object> rresp = rest.postForObject(
                    inferenceBaseUrl + "/api/v1/ecology/rsei", rq, Map.class);
            if (rresp != null && Integer.valueOf(0).equals(rresp.get("code"))) {
                @SuppressWarnings("unchecked")
                Map<String, Object> rd = (Map<String, Object>) rresp.get("data");
                rseiStats = new LinkedHashMap<>();
                rseiStats.put("mean", rd.get("mean"));
                rseiStats.put("levels", rd.get("levels"));
                rseiStats.put("sceneId", rd.get("sceneId"));
                rseiStats.put("datetime", rd.get("datetime"));
                logger.info("RSEI 计算成功：均值={}，日期范围 {}~{}", rd.get("mean"), start, latestDate);
            } else {
                // 非 0 返回（最常见是「该时段无云影像」）也要留痕，否则前端只看到「未计算」不知原因
                Object msg = rresp == null ? "空响应" : rresp.get("message");
                logger.warn("RSEI 返回非成功状态：{}（日期 {}~{}）", msg, start, latestDate);
            }
        } catch (Exception ex) {
            // 生态维度算不出来不应让整个安全评估失败，降级为中性分并在结果里体现
            logger.warn("RSEI 计算失败，生态维度按中性分计入：{}", ex.getMessage());
        }

        // ---- 5. 边坡单元（可选）：让形态维度按「最差单元」聚合，而非全区平均 ----
        List<Map<String, Object>> slopeUnits = new ArrayList<>();
        Map<String, Object> slopeInfo = new LinkedHashMap<>();
        if (withSlope) {
            List<Map<String, Object>> facilityPayload = new ArrayList<>();
            for (String ct : List.of("PIT", "DUMP", "TAILINGS")) {
                List<Map<String, Object>> feats = byClass.get(ct);
                if (feats == null || feats.isEmpty()) continue;
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("classType", ct);
                m.put("features", feats);
                facilityPayload.add(m);
            }
            if (!facilityPayload.isEmpty()) {
                try {
                    Map<String, Object> slopePayload = new LinkedHashMap<>();
                    slopePayload.put("aoi", aoi);
                    slopePayload.put("facilities", facilityPayload);
                    slopePayload.put("zoom", 14);
                    slopePayload.put("maxDim", 512);
                    @SuppressWarnings("unchecked")
                    Map<String, Object> sr = rest.postForObject(
                            inferenceBaseUrl + "/api/v1/slope/analyze", slopePayload, Map.class);
                    if (sr != null && Integer.valueOf(0).equals(sr.get("code"))) {
                        @SuppressWarnings("unchecked")
                        Map<String, Object> sd = (Map<String, Object>) sr.get("data");
                        Object us = sd.get("units");
                        if (us instanceof List<?> list) {
                            for (Object o : list) {
                                if (o instanceof Map<?, ?> mm) {
                                    @SuppressWarnings("unchecked")
                                    Map<String, Object> unit = (Map<String, Object>) mm;
                                    slopeUnits.add(unit);
                                }
                            }
                        }
                        slopeInfo.put("available", Boolean.TRUE.equals(sd.get("available")));
                        slopeInfo.put("unitCount", slopeUnits.size());
                        slopeInfo.put("summary", sd.get("summary"));
                        logger.info("边坡单元识别完成：{} 个单元", slopeUnits.size());
                    }
                } catch (Exception ex) {
                    // 边坡分析失败不阻断评估：形态维度会自动退回全区统计
                    logger.warn("边坡单元识别失败，形态维度退回全区统计：{}", ex.getMessage());
                    slopeInfo.put("available", false);
                    slopeInfo.put("error", ex.getMessage());
                }
            } else {
                slopeInfo.put("available", false);
                slopeInfo.put("reason", "没有采坑/排土场/尾矿记录，无法划分边坡单元");
            }
        }

        // ---- 6. 调 inference 风险接口 ----
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("aoi", aoi);
        payload.put("permitBoundary", permit.isEmpty() ? null : permit);
        payload.put("classes", classesPayload);
        payload.put("trend", trend);
        payload.put("rsei", rseiStats);
        payload.put("withGrid", withGrid);
        payload.put("zoom", 14);
        payload.put("slopeUnits", slopeUnits);

        Map<String, Object> result;
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> resp = rest.postForObject(
                    inferenceBaseUrl + "/api/v1/risk/evaluate",
                    payload, Map.class);
            if (resp == null || !Integer.valueOf(0).equals(resp.get("code"))) {
                return ApiResponse.error(502, "风险评估服务返回异常："
                        + (resp == null ? "空响应" : resp.get("message")));
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> data = (Map<String, Object>) resp.get("data");
            result = data;
        } catch (Exception ex) {
            return ApiResponse.error(502, "风险评估服务不可用：" + ex.getMessage()
                    + "（请确认 inference 服务已启动在 " + inferenceBaseUrl + "）");
        }

        // ---- 7. 补充上下文并记审计 ----
        result.put("available", true);
        // 附带 RSEI 统计：报告页据此写「生态质量评价」章节，无需前端二次调用
        if (rseiStats != null) {
            result.put("rsei", rseiStats);
        }
        // 边坡单元使用情况：前端据此显示「形态维度由 N 个单元聚合」或提示降级原因
        if (!slopeInfo.isEmpty()) {
            result.put("slopeUnits", slopeInfo);
        }
        result.put("projectName", projectName);
        // 让前端与报告能说清「越界基准来自哪」：导入的登记数据 / 项目上临时圈的 / 没有
        result.put("permitSource", permitSource);
        result.put("recordCount", latest.size());
        result.put("generatedAt", java.time.LocalDateTime.now().toString());
        if (trend != null) {
            result.put("trend", trend);
        }
        Object total = result.get("score") instanceof Map<?, ?> sm ? sm.get("total") : null;
        Object level = result.get("score") instanceof Map<?, ?> sm2 ? sm2.get("level") : null;
        auditLogService.record(auth.getName(), "SAFETY_EVALUATE", "PROJECT",
                String.valueOf(projectId),
                "生成安全风险评估：风险分 " + total + "（" + level + "）", null);
        return ApiResponse.ok(result);
    }

    /** 最近一次评估的时间与结论（用于首页/报告展示） */
    @GetMapping("/safety-latest-meta")
    public ApiResponse<Map<String, Object>> latestMeta(@RequestParam(required = false) Long projectId,
                                                       Authentication auth) {
        boolean isAdmin = guard.roleCodesOf(auth).contains("ADMIN");
        List<Extraction> all = extractionService.list(projectId, auth.getName(), isAdmin);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("recordCount", dedupLatest(all).size());
        out.put("hint", "点击「开始评估」生成完整风险结果");
        return ApiResponse.ok(out);
    }

    /**
     * 边坡单元识别与三区扰动（docs/13 阶段一）
     *
     * 只用「采坑/排土场/尾矿」三类设施的边界去圈定边坡带——
     * 植被、水体不构成需要评估的工程边坡。
     */
    @PostMapping("/slope-units")
    public ApiResponse<Map<String, Object>> slopeUnits(
            @RequestParam(required = false) Long projectId,
            Authentication auth) {

        boolean isAdmin = guard.roleCodesOf(auth).contains("ADMIN");
        List<Extraction> all = extractionService.list(projectId, auth.getName(), isAdmin);

        // 分析范围：矿权优先，其次扰动边界，最后外包框
        List<List<Double>> permit = new ArrayList<>();
        List<List<Double>> disturbance = new ArrayList<>();
        if (projectId != null) {
            Project p = projectService.get(projectId);
            projectService.requireAccess(projectId, auth.getName(), isAdmin);
            JsonNode boundary = parseJson(p.getBoundaryJson());
            disturbance = ringOf(boundary, "disturbance");
            // 与安全评估保持同一优先级：导入的登记边界 > 项目手圈边界
            permit = boundaryController.permitRing(projectId);
            if (permit.isEmpty()) {
                permit = ringOf(boundary, "mining");
            }
        }

        // 只取三类设施的几何
        Map<String, List<Map<String, Object>>> facilities = new LinkedHashMap<>();
        for (Extraction e : dedupLatest(all).values()) {
            String ct = e.getClassType();
            if (!"PIT".equals(ct) && !"DUMP".equals(ct) && !"TAILINGS".equals(ct)) {
                continue;
            }
            List<Map<String, Object>> feats = toGeoJsonFeatures(e);
            if (!feats.isEmpty()) {
                facilities.computeIfAbsent(ct, k -> new ArrayList<>()).addAll(feats);
            }
        }

        if (facilities.isEmpty()) {
            Map<String, Object> empty = new LinkedHashMap<>();
            empty.put("available", false);
            empty.put("message", "没有采坑/排土场/尾矿的解译记录，无法划分边坡单元。"
                    + "请先在遥感提取页对这三类地物做提取并保存。");
            return ApiResponse.ok(empty);
        }

        List<List<Double>> aoi = !permit.isEmpty() ? permit
                : (!disturbance.isEmpty() ? disturbance : bboxOf(dedupLatest(all).values()));

        List<Map<String, Object>> facilitiesPayload = new ArrayList<>();
        facilities.forEach((ct, feats) -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("classType", ct);
            m.put("features", feats);
            facilitiesPayload.add(m);
        });

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("aoi", aoi);
        payload.put("facilities", facilitiesPayload);
        payload.put("zoom", 14);
        payload.put("maxDim", 512);

        Map<String, Object> result;
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> resp = rest.postForObject(
                    inferenceBaseUrl + "/api/v1/slope/analyze", payload, Map.class);
            if (resp == null || !Integer.valueOf(0).equals(resp.get("code"))) {
                return ApiResponse.error(502, "边坡分析服务返回异常："
                        + (resp == null ? "空响应" : resp.get("message")));
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> data = (Map<String, Object>) resp.get("data");
            result = data;
        } catch (Exception ex) {
            return ApiResponse.error(502, "边坡分析服务不可用：" + ex.getMessage()
                    + "（请确认 inference 服务已启动在 " + inferenceBaseUrl + "）");
        }

        Object high = result.get("summary") instanceof Map<?, ?> sm ? sm.get("high") : null;
        auditLogService.record(auth.getName(), "SLOPE_UNITS", "PROJECT", String.valueOf(projectId),
                "生成边坡单元识别：高风险单元 " + high + " 个", null);
        return ApiResponse.ok(result);
    }

    // ------------------------------------------------------------------
    // 私有工具
    // ------------------------------------------------------------------

    /** 去重：同一 (类型 | AOI 指纹) 只保留拍摄日期最新的一条 */
    /**
     * 空间关系与专项风险（B6 坑内积水 / B7 尾矿水面 / B8 排土场汇流 / B9 道路切坡 / C4 生态缓冲区 / A3 采坑形态）
     *
     * 这六项的共同点是"两个已有图层叠一下就有结论"，不需要新数据源；
     * 算法放 Python（需要栅格化 + shapely），Java 只负责按当前项目取数。
     */
    @PostMapping("/spatial-relations")
    public ApiResponse<Map<String, Object>> spatialRelations(
            @RequestParam(required = false) Long projectId,
            @RequestParam(defaultValue = "2") double bufferKm,
            @RequestParam(defaultValue = "15") double slopeCutDeg,
            Authentication auth) {

        boolean isAdmin = guard.roleCodesOf(auth).contains("ADMIN");
        List<Extraction> all = extractionService.list(projectId, auth.getName(), isAdmin);
        Map<String, Extraction> latest = dedupLatest(all);
        if (latest.isEmpty()) {
            Map<String, Object> empty = new LinkedHashMap<>();
            empty.put("available", false);
            empty.put("message", "该项目还没有解译记录。请先在「在线解译」提取采坑、排土场、尾矿、道路、水体、植被。");
            return ApiResponse.ok(empty);
        }

        // ---- 分析范围：导入的矿权边界优先，其次项目手圈边界 ----
        List<List<Double>> permit = new ArrayList<>();
        if (projectId != null) {
            Project p = projectService.get(projectId);
            projectService.requireAccess(projectId, auth.getName(), isAdmin);
            permit = boundaryController.permitRing(projectId);
            if (permit.isEmpty()) {
                permit = ringOf(parseJson(p.getBoundaryJson()), "mining");
            }
        }

        // ---- 各类地物：同类型不同 AOI 的记录合并成一组要素 ----
        Map<String, List<Map<String, Object>>> classes = new LinkedHashMap<>();
        for (Extraction e : latest.values()) {
            List<Map<String, Object>> feats = toGeoJsonFeatures(e);
            if (!feats.isEmpty()) {
                classes.computeIfAbsent(e.getClassType(), k -> new ArrayList<>()).addAll(feats);
            }
        }
        if (classes.isEmpty()) {
            Map<String, Object> empty = new LinkedHashMap<>();
            empty.put("available", false);
            empty.put("message", "解译记录里没有可用的面要素（可能是几何为空）");
            return ApiResponse.ok(empty);
        }

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("permit", permit);
        payload.put("classes", classes);
        payload.put("prevWater", previousPeriodFeatures(all, "WATER"));
        payload.put("prevPit", previousPeriodFeatures(all, "PIT"));
        payload.put("bufferKm", Math.max(0.0, Math.min(bufferKm, 10.0)));
        payload.put("slopeCutDeg", Math.max(5.0, Math.min(slopeCutDeg, 45.0)));
        payload.put("zoom", 14);
        payload.put("maxDim", 768);

        Map<String, Object> data;
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> resp = rest.postForObject(
                    inferenceBaseUrl + "/api/v1/spatial/analyze", payload, Map.class);
            if (resp == null || !Integer.valueOf(0).equals(resp.get("code"))) {
                return ApiResponse.error(502, "空间分析服务返回异常："
                        + (resp == null ? "空响应" : resp.get("message")));
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> d = (Map<String, Object>) resp.get("data");
            data = d;
        } catch (Exception ex) {
            return ApiResponse.error(503, "空间分析服务不可用：" + ex.getMessage()
                    + "（请确认 inference 已启动在 " + inferenceBaseUrl + "）");
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("available", true);
        out.put("projectName", projectId == null ? "未指定项目" : projectService.get(projectId).getName());
        out.putAll(data);
        out.put("permitSource", permit.isEmpty() ? "none" : "aoi_boundary_or_project");
        out.put("params", Map.of("bufferKm", bufferKm, "slopeCutDeg", slopeCutDeg));
        out.put("generatedAt", java.time.LocalDateTime.now().toString());
        return ApiResponse.ok(out);
    }

    /** 取某类型的"上一期"全部要素（按拍摄期分组，取倒数第二期）——用于水面/采坑变化判断 */
    private List<Map<String, Object>> previousPeriodFeatures(List<Extraction> all, String classType) {
        List<Extraction> list = all.stream()
                .filter(e -> classType.equals(e.getClassType()))
                .sorted((a, b) -> isNewer(a, b) ? -1 : (isNewer(b, a) ? 1 : 0))
                .toList();
        if (list.isEmpty()) return List.of();
        // 按统计期分组，保持时间倒序
        Map<String, List<Extraction>> byPeriod = new LinkedHashMap<>();
        for (Extraction e : list) {
            byPeriod.computeIfAbsent(periodOf(e), k -> new ArrayList<>()).add(e);
        }
        List<Map<String, Object>> out = new ArrayList<>();
        int idx = 0;
        for (Map.Entry<String, List<Extraction>> entry : byPeriod.entrySet()) {
            idx++;
            if (idx == 2) { // 倒数第二期
                for (Extraction e : entry.getValue()) out.addAll(toGeoJsonFeatures(e));
                break;
            }
        }
        return out;
    }

    private Map<String, Extraction> dedupLatest(List<Extraction> all) {
        Map<String, Extraction> latest = new LinkedHashMap<>();
        for (Extraction e : all) {
            String sig = (e.getAoiSignature() == null || e.getAoiSignature().isBlank())
                    ? "single-" + e.getId()
                    : e.getAoiSignature();
            String key = e.getClassType() + "|" + sig;
            Extraction exist = latest.get(key);
            if (exist == null || isNewer(e, exist)) {
                latest.put(key, e);
            }
        }
        return latest;
    }

    private boolean isNewer(Extraction a, Extraction b) {
        LocalDate da = a.getAcquisitionDate();
        LocalDate db = b.getAcquisitionDate();
        if (da != null && db != null && !da.equals(db)) return da.isAfter(db);
        if (da != null && db == null) return true;
        if (da == null && db != null) return false;
        return a.getId() > b.getId();
    }

    /**
     * 扩张速率等趋势指标
     *
     * 口径：同一 AOI 同一月只取最新一次（与 area-timeseries 一致），
     * 用首末两期算年均速率；采坑另算「等效半径推进速度」——
     * 面积等效为圆，半径年增量即边界平均推进距离，比单纯面积增量直观。
     */
    private Map<String, Object> buildTrend(List<Extraction> all) {
        // 期 | 类型 | AOI 去重
        Map<String, Extraction> dedup = new LinkedHashMap<>();
        for (Extraction e : all) {
            String period = periodOf(e);
            String sig = (e.getAoiSignature() == null || e.getAoiSignature().isBlank())
                    ? "single-" + e.getId()
                    : e.getAoiSignature();
            String key = period + "|" + e.getClassType() + "|" + sig;
            Extraction exist = dedup.get(key);
            if (exist == null || isNewer(e, exist)) {
                dedup.put(key, e);
            }
        }

        // 按期汇总：采坑面积、扰动总面积
        Map<String, double[]> byPeriod = new TreeMap<>();   // [pitHa, disturbedHa]
        for (Extraction e : dedup.values()) {
            double[] agg = byPeriod.computeIfAbsent(periodOf(e), k -> new double[2]);
            double ha = nz(e.getExtractAreaHa());
            if ("PIT".equals(e.getClassType())) {
                agg[0] += ha;
            }
            if (DISTURBED_TYPES.contains(e.getClassType())) {
                agg[1] += ha;
            }
        }
        if (byPeriod.size() < 2) {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("periods", byPeriod.size());
            out.put("note", "期数不足 2 期，无法计算扩张速率");
            return out;
        }

        List<String> periods = new ArrayList<>(byPeriod.keySet());
        String firstKey = periods.get(0);
        String lastKey = periods.get(periods.size() - 1);
        double[] first = byPeriod.get(firstKey);
        double[] last = byPeriod.get(lastKey);

        double years = Math.max(monthsBetween(firstKey, lastKey) / 12.0, 1.0 / 12.0);

        // 首期若没有该类记录（例如 2022 年只提取了建筑、没提采坑），
        // 直接算 (末期-0)/年数 会把速率算虚高，必须标记为不可靠并归零
        boolean pitUnreliable = first[0] <= 0 && last[0] > 0;
        boolean disturbUnreliable = first[1] <= 0 && last[1] > 0;
        double pitGrowth = pitUnreliable ? 0.0 : (last[0] - first[0]) / years;
        double disturbGrowth = disturbUnreliable ? 0.0 : (last[1] - first[1]) / years;

        // 等效半径推进：r = sqrt(A/π)，A 由 ha 换算为 m²
        double r1 = Math.sqrt(Math.max(first[0], 0) * 10000.0 / Math.PI);
        double r2 = Math.sqrt(Math.max(last[0], 0) * 10000.0 / Math.PI);
        double edgeAdvance = pitUnreliable ? 0.0 : (r2 - r1) / years;

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("periods", byPeriod.size());
        out.put("firstPeriod", firstKey);
        out.put("lastPeriod", lastKey);
        out.put("years", round2(years));
        out.put("pitGrowthHaPerYear", round2(pitGrowth));
        out.put("disturbGrowthHaPerYear", round2(disturbGrowth));
        out.put("edgeAdvanceMPerYear", round2(edgeAdvance));
        out.put("reliable", !(pitUnreliable || disturbUnreliable));
        StringBuilder note = new StringBuilder(
                "按同一区域同期取最新一次计算；负值可能代表回填、边界修订或解译口径变化");
        if (pitUnreliable) {
            note.append("；首期无采坑记录，采坑扩张速率不可靠已置零");
        }
        if (disturbUnreliable) {
            note.append("；首期无扰动类记录，扰动新增速率不可靠已置零");
        }
        out.put("note", note.toString());
        return out;
    }

    private static String periodOf(Extraction e) {
        if (e.getAcquisitionDate() != null) {
            return e.getAcquisitionDate().toString().substring(0, 7);
        }
        return e.getYear() != null ? e.getYear() + "-01" : "未知";
    }

    private static double monthsBetween(String a, String b) {
        try {
            int ya = Integer.parseInt(a.substring(0, 4));
            int ma = Integer.parseInt(a.substring(5, 7));
            int yb = Integer.parseInt(b.substring(0, 4));
            int mb = Integer.parseInt(b.substring(5, 7));
            return Math.max(1, (yb - ya) * 12 + (mb - ma));
        } catch (Exception e) {
            return 12;
        }
    }

    /** featuresJson（[[[lng,lat],...],...]）→ GeoJSON Feature 列表 */
    private List<Map<String, Object>> toGeoJsonFeatures(Extraction e) {
        List<Map<String, Object>> out = new ArrayList<>();
        String json = e.getFeaturesJson();
        if (json == null || json.isBlank()) return out;
        try {
            JsonNode arr = mapper.readTree(json);
            if (!arr.isArray()) return out;
            for (JsonNode ring : arr) {
                if (!ring.isArray() || ring.size() < 3) continue;
                Map<String, Object> geometry = new LinkedHashMap<>();
                geometry.put("type", "Polygon");
                geometry.put("coordinates", mapper.convertValue(
                        List.of(mapper.convertValue(ring, List.class)), List.class));
                Map<String, Object> feature = new LinkedHashMap<>();
                feature.put("type", "Feature");
                feature.put("properties", Map.of(
                        "recordId", e.getId(),
                        "classType", e.getClassType(),
                        "date", String.valueOf(e.getAcquisitionDate())));
                feature.put("geometry", geometry);
                out.add(feature);
            }
        } catch (Exception ignored) {
            // 几何解析失败则跳过该记录，不影响其他类型
        }
        return out;
    }

    private JsonNode parseJson(String json) {
        if (json == null || json.isBlank()) return null;
        try {
            return mapper.readTree(json);
        } catch (Exception e) {
            return null;
        }
    }

    private List<List<Double>> ringOf(JsonNode root, String field) {
        List<List<Double>> ring = new ArrayList<>();
        if (root == null) return ring;
        JsonNode arr = root.get(field);
        if (arr == null || !arr.isArray()) return ring;
        for (JsonNode p : arr) {
            if (p.isArray() && p.size() >= 2) {
                ring.add(List.of(p.get(0).asDouble(), p.get(1).asDouble()));
            }
        }
        return ring;
    }

    /** 解译结果的外包矩形（项目没登记边界时的兜底） */
    private List<List<Double>> bboxOf(Iterable<Extraction> items) {
        double minLng = 180, minLat = 90, maxLng = -180, maxLat = -90;
        boolean any = false;
        for (Extraction e : items) {
            for (Map<String, Object> f : toGeoJsonFeatures(e)) {
                Map<?, ?> geom = (Map<?, ?>) f.get("geometry");
                List<?> coords = (List<?>) geom.get("coordinates");
                List<?> ring = (List<?>) coords.get(0);
                for (Object pt : ring) {
                    List<?> p = (List<?>) pt;
                    double lng = ((Number) p.get(0)).doubleValue();
                    double lat = ((Number) p.get(1)).doubleValue();
                    minLng = Math.min(minLng, lng);
                    maxLng = Math.max(maxLng, lng);
                    minLat = Math.min(minLat, lat);
                    maxLat = Math.max(maxLat, lat);
                    any = true;
                }
            }
        }
        if (!any) return new ArrayList<>();
        // 外扩 5% 避免边界贴边
        double dx = (maxLng - minLng) * 0.05;
        double dy = (maxLat - minLat) * 0.05;
        return new ArrayList<>(List.of(
                List.of(minLng - dx, minLat - dy),
                List.of(maxLng + dx, minLat - dy),
                List.of(maxLng + dx, maxLat + dy),
                List.of(minLng - dx, maxLat + dy)));
    }

    private static double nz(Double v) {
        return v == null ? 0.0 : v;
    }

    private static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
