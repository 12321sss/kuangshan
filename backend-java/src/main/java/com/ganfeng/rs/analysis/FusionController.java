package com.ganfeng.rs.analysis;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.BizException;
import com.ganfeng.rs.common.PermissionGuard;
import com.ganfeng.rs.extraction.Extraction;
import com.ganfeng.rs.extraction.ExtractionService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 分类结果 × 指数结果 叠加分析（docs/18）
 *
 * 分工：
 * - Java 按记录 id 从库里取几何（前端只传 id，不传几十万个坐标点）
 * - Python 做几何叠加、IoU、差异斑块、融合与底图
 * - 前端负责图例/标题/比例尺合成与导出
 *
 * 口径：IoU 是两套方法的一致性，不是精度；不一致区域只能建议核查。
 */
@RestController
@RequestMapping("/api/analysis/fusion")
public class FusionController {

    private final ExtractionService extractionService;
    private final PermissionGuard guard;
    private final RestTemplate rest;
    private final ObjectMapper mapper = new ObjectMapper();

    @Value("${INFERENCE_BASE_URL:http://localhost:8010}")
    private String inferenceBaseUrl;

    public FusionController(ExtractionService extractionService,
                            PermissionGuard guard,
                            RestTemplateBuilder builder) {
        this.extractionService = extractionService;
        this.guard = guard;
        this.rest = builder
                .setConnectTimeout(Duration.ofSeconds(10))
                .setReadTimeout(Duration.ofSeconds(120))
                .build();
    }

    /** 配对：某类地物 + 融合策略（未指定策略时默认指数优先） */
    public record Pair(String classType, String strategy) {}

    public record FusionReq(Long projectId,
                            List<Long> classifiedIds,
                            List<Long> indexIds,
                            List<Pair> pairs,
                            Map<String, Object> options,
                            Boolean withImage) {}

    /**
     * 差异分析：只算一致性，不生成新数据
     */
    @PostMapping("/compare")
    public ApiResponse<Map<String, Object>> compare(@RequestBody FusionReq req, Authentication auth) {
        Assembled a = assemble(req, auth);
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("classified", a.classified);
        payload.put("indices", a.indices);
        payload.put("pairs", pairPayload(req.pairs(), a.classified.keySet(), a.indices.keySet()));
        payload.put("options", req.options() == null ? Map.of() : req.options());
        payload.put("withImage", req.withImage() == null || req.withImage());

        Map<String, Object> data = post("/api/v1/fusion/compare", payload, "叠加分析");
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("available", true);
        out.putAll(data);
        out.putAll(a.context());
        return ApiResponse.ok(out);
    }

    /**
     * 融合：按类替换/合并，返回最终几何（不落库，由前端决定是否保存）
     */
    @PostMapping("/merge")
    public ApiResponse<Map<String, Object>> merge(@RequestBody FusionReq req, Authentication auth) {
        if (req.pairs() == null || req.pairs().isEmpty()) {
            throw new BizException(400, "请先做差异分析并选择每类采用的策略");
        }
        Assembled a = assemble(req, auth);
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("classified", a.classified);
        payload.put("indices", a.indices);
        payload.put("pairs", pairPayload(req.pairs(), a.classified.keySet(), a.indices.keySet()));
        payload.put("withImage", req.withImage() == null || req.withImage());

        Map<String, Object> data = post("/api/v1/fusion/merge", payload, "融合");
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("available", true);
        out.putAll(data);
        out.putAll(a.context());
        return ApiResponse.ok(out);
    }

    // ------------------------------------------------------------------
    // 取数与组装
    // ------------------------------------------------------------------

    /** 组装结果：两边按类型合并几何 + 返回给前端的上下文（期次、AOI、是否同期） */
    private record Assembled(Map<String, List<Map<String, Object>>> classified,
                             Map<String, List<Map<String, Object>>> indices,
                             Map<String, Object> context) {}

    private Assembled assemble(FusionReq req, Authentication auth) {
        if (req.projectId() == null) throw new BizException(400, "缺少项目参数");
        guard.requireAccess(req.projectId(), auth);
        boolean isAdmin = guard.roleCodesOf(auth).contains("ADMIN");

        if ((req.classifiedIds() == null || req.classifiedIds().isEmpty())
                || (req.indexIds() == null || req.indexIds().isEmpty())) {
            throw new BizException(400, "请同时选择「分类结果」与「指数结果」");
        }

        List<Extraction> clsList = load(req.classifiedIds(), auth, isAdmin);
        List<Extraction> idxList = load(req.indexIds(), auth, isAdmin);

        Map<String, List<Map<String, Object>>> classified = groupByClass(clsList);
        Map<String, List<Map<String, Object>>> indices = groupByClass(idxList);
        if (classified.isEmpty() || indices.isEmpty()) {
            throw new BizException(400, "所选记录里没有可用几何（可能几何为空）");
        }

        // 期次与 AOI 一致性检查：跨期叠加风险高，必须让用户知情
        String clsDate = earliestDate(clsList);
        String idxDate = earliestDate(idxList);
        Set<String> clsSig = new LinkedHashSet<>();
        Set<String> idxSig = new LinkedHashSet<>();
        for (Extraction e : clsList) if (e.getAoiSignature() != null) clsSig.add(e.getAoiSignature());
        for (Extraction e : idxList) if (e.getAoiSignature() != null) idxSig.add(e.getAoiSignature());

        List<String> warnings = new ArrayList<>();
        if (clsDate != null && idxDate != null && !clsDate.substring(0, 7).equals(idxDate.substring(0, 7))) {
            warnings.add("两套结果不是同一期（分类 " + clsDate + "，指数 " + idxDate
                    + "），叠加差异里会混入真实地表变化，跨期结论需谨慎");
        }
        if (!clsSig.equals(idxSig)) {
            warnings.add("两套结果的 AOI 不完全一致，边界差异会直接体现为「仅分类/仅指数」");
        }

        Map<String, Object> ctx = new LinkedHashMap<>();
        ctx.put("classifiedDate", clsDate);
        ctx.put("indicesDate", idxDate);
        ctx.put("classifiedCount", clsList.size());
        ctx.put("indexCount", idxList.size());
        ctx.put("classifiedClasses", new ArrayList<>(classified.keySet()));
        ctx.put("indexClasses", new ArrayList<>(indices.keySet()));
        ctx.put("warnings", warnings);
        return new Assembled(classified, indices, ctx);
    }

    private List<Extraction> load(List<Long> ids, Authentication auth, boolean isAdmin) {
        List<Extraction> out = new ArrayList<>();
        for (Long id : ids) {
            if (id == null) continue;
            out.add(extractionService.get(id, auth.getName(), isAdmin));
        }
        return out;
    }

    private Map<String, List<Map<String, Object>>> groupByClass(List<Extraction> list) {
        Map<String, List<Map<String, Object>>> out = new LinkedHashMap<>();
        for (Extraction e : list) {
            List<Map<String, Object>> feats = toFeatures(e);
            if (!feats.isEmpty()) {
                out.computeIfAbsent(e.getClassType(), k -> new ArrayList<>()).addAll(feats);
            }
        }
        return out;
    }

    /** featuresJson（环数组）→ GeoJSON Feature 列表 */
    private List<Map<String, Object>> toFeatures(Extraction e) {
        List<Map<String, Object>> out = new ArrayList<>();
        String json = e.getFeaturesJson();
        if (json == null || json.isBlank()) return out;
        try {
            var arr = mapper.readTree(json);
            if (!arr.isArray()) return out;
            for (var ring : arr) {
                if (!ring.isArray() || ring.size() < 3) continue;
                Map<String, Object> geometry = new LinkedHashMap<>();
                geometry.put("type", "Polygon");
                geometry.put("coordinates", mapper.convertValue(
                        List.of(mapper.convertValue(ring, List.class)), List.class));
                Map<String, Object> f = new LinkedHashMap<>();
                f.put("type", "Feature");
                f.put("properties", Map.of("recordId", e.getId(), "classType", e.getClassType()));
                f.put("geometry", geometry);
                out.add(f);
            }
        } catch (Exception ignored) {
            // 单条几何解析失败不影响其它记录
        }
        return out;
    }

    private String earliestDate(List<Extraction> list) {
        LocalDate best = null;
        for (Extraction e : list) {
            LocalDate d = e.getAcquisitionDate();
            if (d != null && (best == null || d.isBefore(best))) best = d;
        }
        return best == null ? null : best.toString();
    }

    /** 只保留两边都有的类型；未给策略的默认指数优先 */
    private List<Map<String, Object>> pairPayload(List<Pair> pairs, Set<String> cls, Set<String> idx) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (pairs != null && !pairs.isEmpty()) {
            for (Pair p : pairs) {
                if (p.classType() == null) continue;
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("classType", p.classType());
                m.put("strategy", p.strategy() == null ? "INDICES_FIRST" : p.strategy());
                out.add(m);
            }
            return out;
        }
        for (String c : cls) {
            if (!idx.contains(c)) continue;
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("classType", c);
            m.put("strategy", "INDICES_FIRST");
            out.add(m);
        }
        return out;
    }

    private Map<String, Object> post(String path, Map<String, Object> payload, String action) {
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> resp = rest.postForObject(inferenceBaseUrl + path, payload, Map.class);
            if (resp == null || !Integer.valueOf(0).equals(resp.get("code"))) {
                throw new BizException(502, action + "服务返回异常：" + (resp == null ? "空响应" : resp.get("message")));
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> data = (Map<String, Object>) resp.get("data");
            return data;
        } catch (RestClientResponseException ex) {
            throw new BizException(400, extractDetail(ex.getResponseBodyAsString(), ex.getMessage()));
        } catch (BizException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new BizException(503, action + "服务不可用：" + ex.getMessage()
                    + "（请确认 inference 已启动在 " + inferenceBaseUrl + "）");
        }
    }

    @SuppressWarnings("unchecked")
    private String extractDetail(String body, String fallback) {
        try {
            Map<String, Object> m = mapper.readValue(body, Map.class);
            Object d = m.get("detail");
            if (d != null) return String.valueOf(d);
        } catch (Exception ignored) {
            // 落回默认
        }
        return fallback;
    }
}
