package com.ganfeng.rs.imagery;

import com.ganfeng.rs.common.BizException;
import com.ganfeng.rs.project.Project;
import com.ganfeng.rs.project.ProjectService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Locale;
import java.util.Set;

/**
 * 影像库服务
 *
 * 坐标系处理原则（本次实现的关键约定）：
 * - 上传时用户**选择**坐标系，imagery.crs 原样记录，不做猜测
 * - 上传影像的覆盖范围（west/south/east/north）**统一以 WGS84 存**，
 *   便于前端 Cesium 直接定位；若用户选了非 4326 的坐标系，
 *   覆盖范围由前端在地图上绘制后随上传请求一并传入（用户已知位置）
 * - 真实解析影像文件头拿 bbox 需要 GDAL，Java 侧无此能力；
 *   生产期可让 inference 服务用 rasterio 读 .prj/.tif 头补齐，
 *   demo 期采用「前端绘制 footprint + 用户选坐标系」的方式
 */
@Service
public class ImageryService {

    /** 上传落盘根目录 */
    private final Path uploadRoot;

    /** 公开数据源支持列表（与 inference 的 BANDS 表对应） */
    private static final Set<String> SOURCES = Set.of("UPLOAD", "SENTINEL2", "LANDSAT9", "GF2");

    /** 常见坐标系选项，供前端下拉选择 */
    public static final List<CoordinateSystem> CRS_OPTIONS = List.of(
            new CoordinateSystem("4326", "WGS84 经纬度", "EPSG:4326"),
            new CoordinateSystem("4490", "CGCS2000 经纬度", "EPSG:4490"),
            new CoordinateSystem("32650", "UTM 北区 50 带（WGS84）", "EPSG:32650"),
            new CoordinateSystem("32649", "UTM 北区 49 带（WGS84）", "EPSG:32649"),
            new CoordinateSystem("4548", "CGCS2000 3 度带 40-43E", "EPSG:4548"),
            new CoordinateSystem("4547", "CGCS2000 3 度带 37-40E", "EPSG:4547"),
            new CoordinateSystem("3857", "Web 墨卡托", "EPSG:3857")
    );

    /** 坐标系选项 DTO */
    public record CoordinateSystem(String code, String name, String label) {}

    private final ImageryRepository repo;

    /** inference 地址：影像元数据自动识别走它（rasterio 在 Python 侧） */
    @org.springframework.beans.factory.annotation.Value("${INFERENCE_BASE_URL:http://localhost:8010}")
    private String inferenceBaseUrl;
    private final ProjectService projectService;

    public ImageryService(ImageryRepository repo, ProjectService projectService,
                          @Value("${app.imagery.upload-dir:./data/imagery}") String uploadDir) {
        this.repo = repo;
        this.projectService = projectService;
        try {
            this.uploadRoot = Paths.get(uploadDir).toAbsolutePath().normalize();
            Files.createDirectories(this.uploadRoot);
        } catch (IOException e) {
            throw new IllegalStateException("无法创建影像上传目录: " + uploadDir, e);
        }
    }

    /**
     * 列表：**必须按项目成员过滤**，否则非成员能看到他人项目的影像
     * （横向越权）。管理员可见全部。
     */
    public List<Imagery> list(Long projectId, String source, String username, boolean isAdmin) {
        // 先算出当前用户可见的项目集合
        var visible = projectService.listForUser(username, isAdmin).stream()
                .map(Project::getId).toList();
        if (visible.isEmpty()) {
            return List.of();
        }
        if (projectId != null) {
            projectService.requireAccess(projectId, username, isAdmin);
        }
        List<Imagery> all = repo.findAll().stream()
                .filter(i -> visible.contains(i.getProjectId()))
                .filter(i -> projectId == null || i.getProjectId().equals(projectId))
                .filter(i -> source == null || source.isBlank()
                        || i.getSource().equalsIgnoreCase(source))
                .sorted(Comparator.comparing(Imagery::getAcquisitionDate).reversed())
                .toList();
        return all;
    }

    /** 读取单条影像，同时校验当前用户对该项目的访问权 */
    public Imagery get(long id, String username, boolean isAdmin) {
        Imagery img = repo.findById(id)
                .orElseThrow(() -> BizException.notFound("影像不存在: " + id));
        projectService.requireAccess(img.getProjectId(), username, isAdmin);
        return img;
    }

    /** 仅按 id 读取（内部回调等已鉴权场景使用） */
    public Imagery get(long id) {
        return repo.findById(id).orElseThrow(() -> BizException.notFound("影像不存在: " + id));
    }

    /**
     * 上传高分影像并入库
     *
     * @param file    影像文件（GeoTIFF 等）
     * @param projectId 所属项目
     * @param name      显示名，为空则用原文件名
     * @param crs       用户选择的坐标系（EPSG 码或 WKT）
     * @param acquisitionDate 拍摄日期
     * @param resolutionM  分辨率（米/像素），为空按 0.8（高分默认）
     * @param bounds    覆盖范围 [west, south, east, north]（WGS84），可为空
     */
    /**
     * 探测影像元数据：先把文件落到 upload 目录，再让 inference 用 rasterio 读
     *
     * 为什么这么做：GeoTIFF 自带 CRS、范围、分辨率、波段数，用户不该手画范围、手填坐标系。
     * 返回 storedPath 供随后的 upload 复用，避免把十几 MB 的文件再传一次。
     */
    public Map<String, Object> probe(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw BizException.badRequest("请选择要上传的影像文件");
        }
        String original = file.getOriginalFilename() == null ? "imagery.tif" : file.getOriginalFilename();
        String storedName = System.currentTimeMillis() + "_" + sanitize(original);
        Path target = uploadRoot.resolve(storedName);
        try (InputStream in = file.getInputStream()) {
            Files.createDirectories(uploadRoot);
            Files.copy(in, target, StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException e) {
            throw BizException.badRequest("影像暂存失败: " + e.getMessage());
        }

        Map<String, Object> meta = inspectByPath(target.toString());
        Map<String, Object> out = new java.util.LinkedHashMap<>(meta);
        out.put("storedPath", target.toString());
        out.put("originalName", original);
        out.put("sizeBytes", file.getSize());
        return out;
    }

    /** 影像预览（贴地图用）：返回 previewBase64 + WGS84 范围 */
    public Map<String, Object> previewOf(Imagery img) {
        String path = resolvePath(img);
        Map<String, Object> meta = inspectByPath(path);
        Map<String, Object> out = new java.util.LinkedHashMap<>();
        out.put("previewBase64", meta.get("previewBase64"));
        out.put("bounds", Map.of(
                "west", img.getWest(), "south", img.getSouth(),
                "east", img.getEast(), "north", img.getNorth()));
        out.put("error", meta.get("error"));
        return out;
    }

    /** 调 inference 读影像元数据；失败返回带 error 的空结果，不阻断上传 */
    @SuppressWarnings("unchecked")
    private Map<String, Object> inspectByPath(String path) {
        try {
            java.net.http.HttpClient client = java.net.http.HttpClient.newBuilder()
                    .connectTimeout(java.time.Duration.ofSeconds(5)).build();
            // 用 GET + URL 编码传路径：Windows 反斜杠在 JSON 里容易转义出错
            String q = java.net.URLEncoder.encode(path, java.nio.charset.StandardCharsets.UTF_8);
            java.net.http.HttpRequest req = java.net.http.HttpRequest
                    .newBuilder(java.net.URI.create(inferenceBaseUrl + "/api/v1/imagery/inspect?path=" + q))
                    .timeout(java.time.Duration.ofSeconds(60))
                    .GET()
                    .build();
            var resp = client.send(req, java.net.http.HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() / 100 != 2) {
                return Map.of("error", "识别失败：HTTP " + resp.statusCode());
            }
            var mapper = new com.fasterxml.jackson.databind.ObjectMapper();
            var node = mapper.readTree(resp.body());
            if (node.path("code").asInt(-1) != 0) {
                return Map.of("error", node.path("message").asText("识别失败"));
            }
            return mapper.convertValue(node.get("data"), Map.class);
        } catch (Exception e) {
            return Map.of("error", "识别服务不可用：" + e.getMessage());
        }
    }

    @Transactional
    public Imagery upload(MultipartFile file, Long projectId, String name, String crs,
                          LocalDate acquisitionDate, Double resolutionM, List<Double> bounds,
                          String existingPath) {
        if ((file == null || file.isEmpty()) && (existingPath == null || existingPath.isBlank())) {
            throw BizException.badRequest("请选择要上传的影像文件");
        }
        if (!SOURCES.contains("UPLOAD")) {
            throw BizException.badRequest("非法来源");
        }

        // ---- 1. 先落盘：要么复用 probe 阶段的暂存文件，要么现在复制 ----
        String original = file == null || file.getOriginalFilename() == null
                ? "imagery.tif" : file.getOriginalFilename();
        Path target;
        if (existingPath != null && !existingPath.isBlank()) {
            // 复用 probe 阶段已存的文件：避免同一份十几 MB 影像传两次
            Path p = Paths.get(existingPath).normalize();
            if (!p.startsWith(uploadRoot.normalize())) {
                throw BizException.badRequest("文件路径不在上传目录内，拒绝使用");
            }
            if (!Files.exists(p)) {
                throw BizException.badRequest("暂存文件已不存在，请重新选择影像");
            }
            target = p;
        } else {
            String storedName = System.currentTimeMillis() + "_" + sanitize(original);
            target = uploadRoot.resolve(storedName);
            try (InputStream in = file.getInputStream()) {
                Files.createDirectories(uploadRoot);
                Files.copy(in, target, StandardCopyOption.REPLACE_EXISTING);
            } catch (IOException e) {
                throw BizException.badRequest("影像文件保存失败: " + e.getMessage());
            }
        }

        // ---- 2. 缺字段就自动识别（GeoTIFF 自带 CRS/范围/分辨率/日期）----
        if (crs == null || crs.isBlank() || acquisitionDate == null
                || bounds == null || bounds.size() != 4 || resolutionM == null) {
            Map<String, Object> meta = inspectByPath(target.toString());
            if (meta.get("error") == null) {
                if (crs == null || crs.isBlank()) {
                    Object c = meta.get("crs");
                    if (c != null) crs = String.valueOf(c);
                }
                if (bounds == null || bounds.size() != 4) {
                    Object b = meta.get("bounds");
                    if (b instanceof Map<?, ?> bm) {
                        bounds = java.util.List.of(
                                ((Number) bm.get("west")).doubleValue(),
                                ((Number) bm.get("south")).doubleValue(),
                                ((Number) bm.get("east")).doubleValue(),
                                ((Number) bm.get("north")).doubleValue());
                    }
                }
                if (acquisitionDate == null && meta.get("acquisitionDate") != null) {
                    try {
                        acquisitionDate = LocalDate.parse(
                                String.valueOf(meta.get("acquisitionDate")).substring(0, 10));
                    } catch (Exception ignored) {
                        // 识别到的日期格式异常就保持为空，由下面的校验提示
                    }
                }
                if (resolutionM == null && meta.get("resolutionM") instanceof Number n) {
                    resolutionM = n.doubleValue();
                }
            }
        }

        // ---- 3. 校验（识别失败时才需要用户手动补）----
        if (crs == null || crs.isBlank()) {
            throw BizException.badRequest(
                    "影像未定义坐标系，且自动识别失败：请手动指定（如 EPSG:4326 / EPSG:32650）");
        }
        if (acquisitionDate == null) {
            throw BizException.badRequest("缺少拍摄日期，且未能从影像或文件名识别：请手动填写");
        }
        if (bounds == null || bounds.size() != 4) {
            throw BizException.badRequest("影像缺少有效范围，且自动识别失败：请手动绘制覆盖范围");
        }
        double west = bounds.get(0), south = bounds.get(1);
        double east = bounds.get(2), north = bounds.get(3);
        if (west >= east || south >= north) {
            throw BizException.badRequest("覆盖范围无效：需满足 west < east 且 south < north");
        }
        if (south < -90 || north > 90 || west < -180 || east > 180) {
            throw BizException.badRequest("覆盖范围需在合法经纬度内（-180~180 / -90~90）");
        }

        Imagery img = new Imagery();
        img.setProjectId(projectId);
        img.setName(name == null || name.isBlank() ? original : name.trim());
        img.setSource("UPLOAD");
        img.setFilePath(target.toString());
        img.setOriginalName(original);
        img.setCrs(crs.trim());
        img.setAcquisitionDate(acquisitionDate);
        img.setResolutionM(resolutionM == null ? 0.8 : resolutionM);
        img.setWest(round6(west));
        img.setSouth(round6(south));
        img.setEast(round6(east));
        img.setNorth(round6(north));
        img.setStatus("READY");
        img.setNote("用户上传影像，坐标系 " + crs.trim());
        return repo.save(img);
    }

    /** 登记一景公开数据（Sentinel-2 检索结果入库）
     *  filePath 可选：公开数据下载到本地缓存后回填，后续即可直接解译 */
    @Transactional
    public Imagery registerPublic(Long projectId, String name, String source, String productId,
                                  LocalDate acquisitionDate, Double cloudCover,
                                  double west, double south, double east, double north,
                                  double resM, String note, String filePath) {
        if (!SOURCES.contains(source.toUpperCase(Locale.ROOT))) {
            throw BizException.badRequest("非法数据源: " + source);
        }
        Imagery img = new Imagery();
        img.setProjectId(projectId);
        img.setName(name);
        img.setSource(source.toUpperCase(Locale.ROOT));
        img.setProductId(productId);
        img.setAcquisitionDate(acquisitionDate);
        img.setCloudCover(cloudCover);
        img.setResolutionM(resM);
        img.setWest(round6(west));
        img.setSouth(round6(south));
        img.setEast(round6(east));
        img.setNorth(round6(north));
        img.setCrs("EPSG:4326");
        img.setFilePath(filePath);
        img.setStatus("READY");
        img.setNote(note);
        return repo.save(img);
    }

    /** 保存影像变更（收藏标记等轻量字段更新） */
    @Transactional
    public Imagery save(Imagery img) {
        return repo.save(img);
    }

    /**
     * 更新影像档案元数据（方案附录 B）
     *
     * 单独一个入口而不是塞进上传表单：供应商、授权范围、单价这类信息
     * 往往是影像入库后才拿到的（走采购/法务流程），上传时未必齐全。
     * 这里做白名单 + 范围校验，避免把"离轴角 999 度"这种脏数据写进档案。
     */
    @Transactional
    public Imagery updateMetadata(long id, java.util.Map<String, Object> meta,
                                  String username, boolean isAdmin) {
        Imagery img = get(id, username, isAdmin);
        if (meta == null || meta.isEmpty()) {
            throw BizException.badRequest("没有需要更新的元数据");
        }

        if (meta.containsKey("offNadirAngle")) {
            img.setOffNadirAngle(range(meta.get("offNadirAngle"), 0, 65, "离轴角"));
        }
        if (meta.containsKey("sunElevation")) {
            img.setSunElevation(range(meta.get("sunElevation"), 0, 90, "太阳高度角"));
        }
        if (meta.containsKey("sunAzimuth")) {
            img.setSunAzimuth(range(meta.get("sunAzimuth"), 0, 360, "太阳方位角"));
        }
        if (meta.containsKey("orthoLevel")) {
            img.setOrthoLevel(oneOf(meta.get("orthoLevel"),
                    java.util.List.of("RAW", "L1T", "L2A", "ORTHO", "OTHER"), "正射等级"));
        }
        if (meta.containsKey("licenseScope")) {
            img.setLicenseScope(oneOf(meta.get("licenseScope"),
                    java.util.List.of("INTERNAL", "TRAIN", "PUBLISH", "CROSS_BORDER"), "授权范围"));
        }
        if (meta.containsKey("vendor")) {
            img.setVendor(text(meta.get("vendor"), 128, "供应商"));
        }
        if (meta.containsKey("price")) {
            img.setPrice(range(meta.get("price"), 0, 1e10, "价格"));
        }
        if (meta.containsKey("priceCurrency")) {
            img.setPriceCurrency(oneOf(meta.get("priceCurrency"),
                    java.util.List.of("CNY", "USD", "EUR"), "币种"));
        }
        if (meta.containsKey("orderNo")) {
            img.setOrderNo(text(meta.get("orderNo"), 64, "采购单号"));
        }
        if (meta.containsKey("deliveryDate")) {
            Object v = meta.get("deliveryDate");
            if (v == null || String.valueOf(v).isBlank()) {
                img.setDeliveryDate(null);
            } else {
                try {
                    img.setDeliveryDate(java.time.LocalDate.parse(String.valueOf(v).substring(0, 10)));
                } catch (Exception e) {
                    throw BizException.badRequest("交付日期格式应为 YYYY-MM-DD");
                }
            }
        }
        if (meta.containsKey("bandCount")) {
            Object v = meta.get("bandCount");
            if (v == null || String.valueOf(v).isBlank()) {
                img.setBandCount(null);
            } else {
                Double n = range(v, 1, 200, "波段数");
                img.setBandCount(n == null ? null : n.intValue());
            }
        }
        if (meta.containsKey("sensorName")) {
            img.setSensorName(text(meta.get("sensorName"), 32, "传感器"));
        }
        return repo.save(img);
    }

    /** 数值范围校验（空值允许，表示清空该字段） */
    private Double range(Object v, double min, double max, String label) {
        if (v == null || String.valueOf(v).isBlank()) return null;
        double d;
        try {
            d = Double.parseDouble(String.valueOf(v));
        } catch (NumberFormatException e) {
            throw BizException.badRequest(label + "必须是数字");
        }
        if (d < min || d > max) {
            throw BizException.badRequest(label + "应在 " + (int) min + " ~ " + (int) max + " 之间");
        }
        return d;
    }

    private String oneOf(Object v, java.util.List<String> allowed, String label) {
        if (v == null || String.valueOf(v).isBlank()) return null;
        String s = String.valueOf(v).trim().toUpperCase();
        if (!allowed.contains(s)) {
            throw BizException.badRequest(label + "只能是：" + String.join(" / ", allowed));
        }
        return s;
    }

    private String text(Object v, int maxLen, String label) {
        if (v == null) return null;
        String s = String.valueOf(v).trim();
        if (s.isEmpty()) return null;
        if (s.length() > maxLen) {
            throw BizException.badRequest(label + "不能超过 " + maxLen + " 个字符");
        }
        return s;
    }

    @Transactional
    public void delete(long id) {
        Imagery img = get(id);        // 仅删除本地上传文件；公开数据源无本地文件
        if (img.getFilePath() != null && !img.getFilePath().isBlank()) {
            try {
                Files.deleteIfExists(Paths.get(img.getFilePath()));
            } catch (IOException ignored) {
                // 文件删除失败不阻断业务记录删除
            }
        }
        repo.delete(img);
    }

    /** 解析上传文件的绝对路径，供 inference 读取 */
    public String resolvePath(Imagery img) {
        if (img.getFilePath() == null || img.getFilePath().isBlank()) {
            throw BizException.badRequest("该影像无本地文件，无法解译：" + img.getName());
        }
        Path p = Paths.get(img.getFilePath());
        if (!Files.exists(p)) {
            throw BizException.badRequest("影像文件不存在或已被删除：" + img.getOriginalName());
        }
        return p.toAbsolutePath().normalize().toString();
    }

    private static String sanitize(String name) {
        String base = name.replace('\\', '/');
        int idx = base.lastIndexOf('/');
        if (idx >= 0) {
            base = base.substring(idx + 1);
        }
        return base.replaceAll("[^A-Za-z0-9._-]", "_");
    }

    private static double round6(double v) {
        return BigDecimal.valueOf(v).setScale(6, RoundingMode.HALF_UP).doubleValue();
    }
}