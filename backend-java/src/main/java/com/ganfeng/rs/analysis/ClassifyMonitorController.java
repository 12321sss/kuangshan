package com.ganfeng.rs.analysis;

import com.ganfeng.rs.boundary.AoiBoundaryController;
import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.BizException;
import com.ganfeng.rs.common.PermissionGuard;
import com.ganfeng.rs.project.Project;
import com.ganfeng.rs.project.ProjectService;
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
 * 精细解译与周尺度监测的转发层
 *
 * 三件事都在 Python 侧算（栅格 + sklearn + STAC），Java 只负责：
 * ① 项目权限校验；② 从「边界管理」取分析区；③ 把 inference 的错误信息原样带回前端。
 *
 * 为什么分析区默认取矿权边界：解译/分类都要一个明确范围，
 * 让用户每次手输坐标既不专业也容易错；导入过 SHP 的项目应直接复用。
 */
@RestController
@RequestMapping("/api/analysis")
public class ClassifyMonitorController {

    private final ProjectService projectService;
    private final PermissionGuard guard;
    private final AoiBoundaryController boundaryController;
    private final RestTemplate rest;

    @Value("${INFERENCE_BASE_URL:http://localhost:8010}")
    private String inferenceBaseUrl;

    public ClassifyMonitorController(ProjectService projectService,
                                     PermissionGuard guard,
                                     AoiBoundaryController boundaryController,
                                     RestTemplateBuilder builder) {
        this.projectService = projectService;
        this.guard = guard;
        this.boundaryController = boundaryController;
        // 首次跑监督分类/突变检测要下载影像瓦片，单景 4 波段可能 1-4 分钟
        this.rest = builder
                .setConnectTimeout(Duration.ofSeconds(10))
                .setReadTimeout(Duration.ofSeconds(420))
                .build();
    }

    /** 可用的分析区：导入的边界 + 历史解译记录用过的大致范围提示 */
    @GetMapping("/aoi-options")
    public ApiResponse<Map<String, Object>> aoiOptions(@RequestParam(required = false) Long projectId,
                                                       Authentication auth) {
        Map<String, Object> out = new LinkedHashMap<>();
        if (projectId == null) {
            out.put("options", List.of());
            return ApiResponse.ok(out);
        }
        boolean isAdmin = guard.roleCodesOf(auth).contains("ADMIN");
        projectService.requireAccess(projectId, auth.getName(), isAdmin);

        List<Map<String, Object>> options = new ArrayList<>();
        // 导入的边界：带类型与面积，前端直接下拉选
        for (Map<String, Object> b : boundaryList(projectId)) {
            options.add(b);
        }
        out.put("options", options);
        out.put("permitAreaNote", options.isEmpty()
                ? "该项目还没有导入边界。请先到「遥感解译 → 边界管理」导入矿权范围（SHP/GeoJSON/KML）"
                : "");
        return ApiResponse.ok(out);
    }

    /** 内部：把 boundary 列表转成前端下拉用的结构（含几何，省一次请求） */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> boundaryList(Long projectId) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> b : boundaryController.listForProject(projectId)) {
            Object geom = b.get("geometry");
            if (!(geom instanceof Map<?, ?> g)) continue;
            Object outer = g.get("outer");
            if (!(outer instanceof List<?> ring) || ring.size() < 3) continue;
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", b.get("id"));
            item.put("name", b.get("name"));
            item.put("boundaryType", b.get("boundaryType"));
            item.put("areaHa", b.get("areaHa"));
            item.put("ring", outer);
            out.add(item);
        }
        return out;
    }

    // ------------------------------------------------------------------
    // 监督分类
    // ------------------------------------------------------------------

    public record SamplePoint(String classType, double lng, double lat) {}

    public record ClassifyReq(Long projectId, List<List<Double>> aoi,
                              List<SamplePoint> samples, String start, String end,
                              Double maxCloud, Integer maxDim, Integer minSamples) {}

    @PostMapping("/classify-supervised")
    public ApiResponse<Map<String, Object>> classifySupervised(@RequestBody ClassifyReq req,
                                                              Authentication auth) {
        if (req.projectId() == null) throw new BizException(400, "缺少项目参数");
        List<List<Double>> aoi = resolveAoi(req.projectId(), req.aoi(), auth);
        if (req.samples() == null || req.samples().isEmpty()) {
            throw new BizException(400, "还没有样本点：请先在图上一类一类地点选样本");
        }

        List<Map<String, Object>> samples = new ArrayList<>();
        for (SamplePoint s : req.samples()) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("classType", s.classType());
            m.put("lng", s.lng());
            m.put("lat", s.lat());
            samples.add(m);
        }

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("aoi", aoi);
        payload.put("samples", samples);
        payload.put("start", req.start());
        payload.put("end", req.end());
        payload.put("maxCloud", req.maxCloud() == null ? 20 : req.maxCloud());
        payload.put("maxDim", req.maxDim() == null ? 1024 : req.maxDim());
        payload.put("minSamples", req.minSamples() == null ? 8 : req.minSamples());

        Map<String, Object> data = post("/api/v1/classify/supervised", payload, "监督分类");
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("available", true);
        out.put("projectName", projectService.get(req.projectId()).getName());
        out.putAll(data);
        return ApiResponse.ok(out);
    }

    // ------------------------------------------------------------------
    // L1 / L2
    // ------------------------------------------------------------------

    public record AvailabilityReq(Long projectId, List<List<Double>> aoi,
                                  Integer days, Double maxCloud) {}

    @PostMapping("/monitor-availability")
    public ApiResponse<Map<String, Object>> monitorAvailability(@RequestBody AvailabilityReq req,
                                                                Authentication auth) {
        if (req.projectId() == null) throw new BizException(400, "缺少项目参数");
        List<List<Double>> aoi = resolveAoi(req.projectId(), req.aoi(), auth);
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("aoi", aoi);
        payload.put("days", req.days() == null ? 30 : req.days());
        payload.put("maxCloud", req.maxCloud() == null ? 20 : req.maxCloud());
        return ApiResponse.ok(post("/api/v1/monitor/availability", payload, "影像可用性检查"));
    }

    public record ChangeReq(Long projectId, List<List<Double>> aoi,
                            String d1Start, String d1End, String d2Start, String d2End,
                            Double maxCloud, Double minAreaHa, Boolean withImage) {}

    @PostMapping("/change-events")
    public ApiResponse<Map<String, Object>> changeEvents(@RequestBody ChangeReq req,
                                                          Authentication auth) {
        if (req.projectId() == null) throw new BizException(400, "缺少项目参数");
        if (req.d1Start() == null || req.d1End() == null || req.d2Start() == null || req.d2End() == null) {
            throw new BizException(400, "两期都要给日期范围");
        }
        List<List<Double>> aoi = resolveAoi(req.projectId(), req.aoi(), auth);
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("aoi", aoi);
        payload.put("d1Start", req.d1Start());
        payload.put("d1End", req.d1End());
        payload.put("d2Start", req.d2Start());
        payload.put("d2End", req.d2End());
        payload.put("maxCloud", req.maxCloud() == null ? 20 : req.maxCloud());
        payload.put("minAreaHa", req.minAreaHa() == null ? 0.5 : req.minAreaHa());
        payload.put("withImage", req.withImage() == null || req.withImage());
        return ApiResponse.ok(post("/api/v1/monitor/change-events", payload, "突变检测"));
    }

    // ------------------------------------------------------------------
    // 工具
    // ------------------------------------------------------------------

    /** 前端没传 aoi 时，用项目导入的矿权边界 */
    private List<List<Double>> resolveAoi(Long projectId, List<List<Double>> given, Authentication auth) {
        guard.requireAccess(projectId, auth);
        if (given != null && given.size() >= 3) return given;
        List<List<Double>> permit = boundaryController.permitRing(projectId);
        if (permit.size() >= 3) return permit;
        throw new BizException(400,
                "缺少分析范围：请先到「边界管理」导入矿权边界，或在页面上选择一条边界");
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> post(String path, Map<String, Object> payload, String actionName) {
        try {
            Map<String, Object> resp = rest.postForObject(inferenceBaseUrl + path, payload, Map.class);
            if (resp == null || !Integer.valueOf(0).equals(resp.get("code"))) {
                throw new BizException(502, actionName + "服务返回异常："
                        + (resp == null ? "空响应" : resp.get("message")));
            }
            return (Map<String, Object>) resp.get("data");
        } catch (RestClientResponseException ex) {
            // 400 的 detail 里是人类可读原因（样本不足 / 无影像等），原样带给前端
            throw new BizException(400, extractDetail(ex.getResponseBodyAsString(), ex.getMessage()));
        } catch (BizException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new BizException(503, actionName + "服务不可用：" + ex.getMessage()
                    + "（请确认 inference 已启动在 " + inferenceBaseUrl + "）");
        }
    }

    @SuppressWarnings("unchecked")
    private String extractDetail(String body, String fallback) {
        try {
            com.fasterxml.jackson.databind.ObjectMapper m = new com.fasterxml.jackson.databind.ObjectMapper();
            Map<String, Object> map = m.readValue(body, Map.class);
            Object d = map.get("detail");
            if (d != null) return String.valueOf(d);
        } catch (Exception ignored) {
            // 落回默认
        }
        return fallback;
    }
}
