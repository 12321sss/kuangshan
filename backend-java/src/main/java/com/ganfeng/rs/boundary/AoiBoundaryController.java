package com.ganfeng.rs.boundary;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.BizException;
import com.ganfeng.rs.common.PermissionGuard;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 边界管理：把客户给的 SHP/GeoJSON/KML 转成平台可用的 AOI
 *
 * 分工：
 * - 解析与坐标系转换放 Python（pyshp + rasterio CRS），Java 不引 GDAL 绑定；
 * - Java 负责落库、项目隔离、权限校验，并把边界喂给越界检测与提取任务。
 *
 * 口径红线（docs/12）：导入的是「矿权/项目范围」，与「实际扰动边界」必须分开存，
 * 越界检测只认 boundaryType=PERMIT。
 */
@RestController
@RequestMapping("/api/aoi-boundaries")
public class AoiBoundaryController {

    private static final List<String> VALID_TYPES = List.of("PERMIT", "DISTURBANCE", "ECO");

    private final AoiBoundaryRepository repo;
    private final PermissionGuard guard;
    private final RestTemplate rest;
    private final ObjectMapper json = new ObjectMapper();

    @Value("${INFERENCE_BASE_URL:http://localhost:8010}")
    private String inferenceBaseUrl;

    public AoiBoundaryController(AoiBoundaryRepository repo, PermissionGuard guard,
                                 RestTemplateBuilder builder) {
        this.repo = repo;
        this.guard = guard;
        // 边界解析要解压+投影转换，给足超时
        this.rest = builder
                .setConnectTimeout(Duration.ofSeconds(10))
                .setReadTimeout(Duration.ofSeconds(120))
                .build();
    }

    /** 列表：可按类型过滤 */
    @GetMapping
    public ApiResponse<List<Map<String, Object>>> list(@RequestParam Long projectId,
                                                       @RequestParam(required = false) String type,
                                                       Authentication auth) {
        guard.requireAccess(projectId, auth);
        List<AoiBoundary> rows = (type == null || type.isBlank())
                ? repo.findByProjectIdOrderByCreatedAtDesc(projectId)
                : repo.findByProjectIdAndBoundaryTypeOrderByCreatedAtDesc(projectId, type);
        List<Map<String, Object>> out = new ArrayList<>();
        for (AoiBoundary b : rows) out.add(brief(b));
        return ApiResponse.ok(out);
    }

    /** 单条详情（含完整几何，前端预览用） */
    @GetMapping("/{id}")
    public ApiResponse<Map<String, Object>> get(@PathVariable long id, Authentication auth) {
        AoiBoundary b = repo.findById(id)
                .orElseThrow(() -> new BizException(404, "边界不存在"));
        guard.requireAccess(b.getProjectId(), auth);
        Map<String, Object> out = brief(b);
        out.put("geometry", readGeometry(b.getGeometryJson()));
        return ApiResponse.ok(out);
    }

    /** 项目边界概况：给安全评估页提示「越界检测是否有基准可用」 */
    @GetMapping("/summary")
    public ApiResponse<Map<String, Object>> summary(@RequestParam Long projectId,
                                                    Authentication auth) {
        guard.requireAccess(projectId, auth);
        List<AoiBoundary> rows = repo.findByProjectIdOrderByCreatedAtDesc(projectId);
        long permit = rows.stream().filter(b -> "PERMIT".equals(b.getBoundaryType())).count();
        long disturb = rows.stream().filter(b -> "DISTURBANCE".equals(b.getBoundaryType())).count();
        long eco = rows.stream().filter(b -> "ECO".equals(b.getBoundaryType())).count();
        double permitArea = rows.stream().filter(b -> "PERMIT".equals(b.getBoundaryType()))
                .mapToDouble(AoiBoundary::getAreaHa).sum();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("total", rows.size());
        out.put("permit", permit);
        out.put("disturbance", disturb);
        out.put("eco", eco);
        out.put("permitAreaHa", Math.round(permitArea * 100) / 100.0);
        out.put("encroachReady", permit > 0);
        out.put("hint", permit > 0
                ? "已登记矿权范围，越界开采检测可用"
                : "尚未登记矿权范围，越界开采检测不可用（请导入客户提供的矿权边界）");
        return ApiResponse.ok(out);
    }

    public record ImportReq(Long projectId, String boundaryType, String filename,
                            String contentBase64, String name,
                            Boolean merge) {}

    /**
     * 导入边界文件
     *
     * merge=true 时把多个要素合并成一条（按最小外接矩形近似，用于「整个矿区算一个范围」）；
     * 默认 false，一个要素一条记录，便于逐块管理。
     */
    @PostMapping("/import")
    public ApiResponse<Map<String, Object>> importFile(@RequestBody ImportReq req,
                                                       Authentication auth) {
        if (req.projectId() == null) throw new BizException(400, "缺少项目参数");
        guard.requireAccess(req.projectId(), auth);
        guard.require(auth, "action:imagery-manage");

        String type = (req.boundaryType() == null || req.boundaryType().isBlank())
                ? "PERMIT" : req.boundaryType().trim().toUpperCase();
        if (!VALID_TYPES.contains(type)) {
            throw new BizException(400, "边界类型只能是 PERMIT（矿权范围）/ DISTURBANCE（扰动边界）/ ECO（生态缓冲区）");
        }
        if (req.contentBase64() == null || req.contentBase64().isBlank()) {
            throw new BizException(400, "文件内容为空");
        }

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("filename", req.filename());
        payload.put("contentBase64", req.contentBase64());

        Map<String, Object> data;
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> resp = rest.postForObject(
                    inferenceBaseUrl + "/api/v1/aoi/import", payload, Map.class);
            if (resp == null || !Integer.valueOf(0).equals(resp.get("code"))) {
                throw new BizException(502, "边界解析服务返回异常：" + resp);
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> d = (Map<String, Object>) resp.get("data");
            data = d;
        } catch (RestClientResponseException ex) {
            throw new BizException(400, extractDetail(ex.getResponseBodyAsString(), ex.getMessage()));
        } catch (BizException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new BizException(503, "边界解析服务不可用：" + ex.getMessage()
                    + "（请确认 inference 已启动在 " + inferenceBaseUrl + "）");
        }

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> features = (List<Map<String, Object>>) data.get("features");
        if (features == null || features.isEmpty()) {
            throw new BizException(400, "文件中没有可用的面要素");
        }

        String sourceFormat = String.valueOf(data.getOrDefault("sourceFormat", ""));
        String sourceCrs = String.valueOf(data.getOrDefault("sourceCrs", ""));
        String warnings = String.join("；", asStringList(data.get("warnings")));
        String userName = auth.getName();

        List<Map<String, Object>> saved = new ArrayList<>();
        boolean merge = Boolean.TRUE.equals(req.merge());

        if (merge && features.size() > 1) {
            // 合并：把多个外环拼成一条记录的 outer（前端按多环渲染；面积取并集近似=各面积之和去掉重叠不可得）
            List<List<Double>> allPts = new ArrayList<>();
            double area = 0;
            int verts = 0;
            for (Map<String, Object> f : features) {
                area += toDouble(f.get("areaHa"));
                verts += (int) toDouble(f.get("vertexCount"));
                allPts.addAll(asPoints(f.get("outer")));
            }
            Map<String, Object> geom = new LinkedHashMap<>();
            geom.put("outer", allPts);
            geom.put("holes", List.of());
            geom.put("multiFeature", true);
            AoiBoundary b = new AoiBoundary(req.projectId(),
                    pickName(req.name(), "合并边界"), type, writeJson(geom),
                    round4(area), verts, sourceFormat, sourceCrs, req.filename(),
                    warnings, userName);
            repo.save(b);
            saved.add(brief(b));
        } else {
            int idx = 1;
            for (Map<String, Object> f : features) {
                Map<String, Object> geom = new LinkedHashMap<>();
                geom.put("outer", f.get("outer"));
                geom.put("holes", f.getOrDefault("holes", List.of()));

                String nm = req.name();
                if (nm == null || nm.isBlank()) {
                    nm = String.valueOf(f.getOrDefault("name", "边界"));
                }
                if (features.size() > 1 && (req.name() == null || req.name().isBlank())) {
                    nm = nm + "（" + idx + "/" + features.size() + "）";
                }
                idx++;

                AoiBoundary b = new AoiBoundary(req.projectId(), trim(nm, 120), type,
                        writeJson(geom), round4(toDouble(f.get("areaHa"))),
                        (int) toDouble(f.get("vertexCount")), sourceFormat, sourceCrs,
                        req.filename(), warnings, userName);
                repo.save(b);
                saved.add(brief(b));
            }
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("saved", saved);
        out.put("count", saved.size());
        out.put("sourceFormat", sourceFormat);
        out.put("sourceCrs", sourceCrs);
        out.put("warnings", warnings);
        out.put("boundaryType", type);
        return ApiResponse.ok(out);
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(@PathVariable long id, Authentication auth) {
        AoiBoundary b = repo.findById(id).orElseThrow(() -> new BizException(404, "边界不存在"));
        guard.requireAccess(b.getProjectId(), auth);
        guard.require(auth, "action:imagery-manage");
        repo.delete(b);
        return ApiResponse.ok(null);
    }

    // ------------------------------------------------------------------
    // 供其他模块复用：取某项目的矿权外环（越界检测基准）
    // ------------------------------------------------------------------

    /**
     * 带几何的边界列表（不做权限校验，调用方必须自己校验项目访问权）。
     * 分析类页面需要一次拿到「名称 + 类型 + 面积 + 外环」做下拉选择，避免 N+1 请求。
     */
    public List<Map<String, Object>> listForProject(Long projectId) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (AoiBoundary b : repo.findByProjectIdOrderByCreatedAtDesc(projectId)) {
            Map<String, Object> m = brief(b);
            m.put("geometry", readGeometry(b.getGeometryJson()));
            out.add(m);
        }
        return out;
    }

    /** 取最大的那条矿权边界的外环；没有则返回空列表 */
    public List<List<Double>> permitRing(Long projectId) {
        List<AoiBoundary> rows = repo.findByProjectIdAndBoundaryTypeOrderByCreatedAtDesc(projectId, "PERMIT");
        if (rows.isEmpty()) return List.of();
        AoiBoundary best = rows.stream()
                .max((a, b) -> Double.compare(a.getAreaHa(), b.getAreaHa()))
                .orElse(rows.get(0));
        Object geom = readGeometry(best.getGeometryJson());
        if (!(geom instanceof Map<?, ?> g)) return List.of();
        return asPoints(g.get("outer"));
    }

    // ---- 工具 ----

    private Map<String, Object> brief(AoiBoundary b) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", b.getId());
        m.put("projectId", b.getProjectId());
        m.put("name", b.getName());
        m.put("boundaryType", b.getBoundaryType());
        m.put("areaHa", b.getAreaHa());
        m.put("vertexCount", b.getVertexCount());
        m.put("sourceFormat", b.getSourceFormat());
        m.put("sourceCrs", b.getSourceCrs());
        m.put("sourceFile", b.getSourceFile());
        m.put("warnings", b.getWarnings());
        m.put("createdBy", b.getCreatedBy());
        m.put("createdAt", b.getCreatedAt() == null ? null : b.getCreatedAt().toString());
        return m;
    }

    private Object readGeometry(String s) {
        try {
            return json.readValue(s == null ? "{}" : s, Object.class);
        } catch (Exception e) {
            return Map.of();
        }
    }

    private String writeJson(Object o) {
        try {
            return json.writeValueAsString(o);
        } catch (Exception e) {
            return "{}";
        }
    }

    @SuppressWarnings("unchecked")
    private List<List<Double>> asPoints(Object raw) {
        List<List<Double>> out = new ArrayList<>();
        if (!(raw instanceof List<?> list)) return out;
        for (Object p : list) {
            if (p instanceof List<?> pair && pair.size() >= 2) {
                out.add(List.of(((Number) pair.get(0)).doubleValue(),
                        ((Number) pair.get(1)).doubleValue()));
            }
        }
        return out;
    }

    @SuppressWarnings("unchecked")
    private List<String> asStringList(Object raw) {
        List<String> out = new ArrayList<>();
        if (raw instanceof List<?> list) {
            for (Object o : list) if (o != null) out.add(String.valueOf(o));
        }
        return out;
    }

    /** 从 inference 的 400 响应里取 detail，避免把整段 HTML 抛给前端 */
    @SuppressWarnings("unchecked")
    private String extractDetail(String body, String fallback) {
        try {
            Map<String, Object> m = json.readValue(body, Map.class);
            Object d = m.get("detail");
            if (d != null) return String.valueOf(d);
        } catch (Exception ignored) {
            // 落回默认信息
        }
        return fallback;
    }

    private double toDouble(Object o) {
        return o instanceof Number n ? n.doubleValue() : 0.0;
    }

    private double round4(double v) {
        return Math.round(v * 10000.0) / 10000.0;
    }

    private String pickName(String given, String fallback) {
        return (given == null || given.isBlank()) ? fallback : trim(given, 120);
    }

    private String trim(String s, int max) {
        if (s == null) return "";
        return s.length() <= max ? s : s.substring(0, max);
    }
}
