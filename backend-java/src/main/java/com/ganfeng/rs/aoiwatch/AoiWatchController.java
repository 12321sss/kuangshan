package com.ganfeng.rs.aoiwatch;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.BizException;
import com.ganfeng.rs.common.PermissionGuard;
import com.ganfeng.rs.extraction.Extraction;
import com.ganfeng.rs.extraction.ExtractionRepository;
import com.ganfeng.rs.extraction.ExtractionService;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * AOI 监测订阅：客户圈一块关注区域，系统持续跟踪该区域的地物变化。
 *
 * 价值：把「每次手动圈 AOI 解译」变成「圈一次、持续盯」——这是客户最核心的主动操作诉求。
 *
 * 实现：复用 extractions 表按 aoiSignature 分组的历史记录。
 * 每次检查取该区域同地物类型的最近两期，比较面积差并给出变化结论。
 */
@RestController
@RequestMapping("/api/aoi-watch")
public class AoiWatchController {

    private final AoiWatchRepository repo;
    private final ExtractionRepository extractionRepo;
    private final PermissionGuard guard;

    public AoiWatchController(AoiWatchRepository repo, ExtractionRepository extractionRepo,
                              PermissionGuard guard) {
        this.repo = repo;
        this.extractionRepo = extractionRepo;
        this.guard = guard;
    }

    /** 列表：每条关注区附带该区域的最新解译概况（期数/最新日期/最新面积） */
    @GetMapping
    public ApiResponse<List<Map<String, Object>>> list(@RequestParam Long projectId,
                                                       Authentication auth) {
        guard.requireAccess(projectId, auth);
        boolean isAdmin = guard.isAdmin(auth);
        List<AoiWatch> watches = isAdmin
                ? repo.findByProjectIdOrderByIdDesc(projectId)
                : repo.findByProjectIdAndUsernameOrderByIdDesc(projectId, auth.getName());

        List<Map<String, Object>> out = new ArrayList<>();
        for (AoiWatch w : watches) {
            Map<String, Object> m = new HashMap<>();
            m.put("id", w.getId());
            m.put("name", w.getName());
            m.put("classType", w.getClassType());
            m.put("aoiJson", w.getAoiJson());
            m.put("signature", w.getSignature());
            m.put("createdAt", w.getCreatedAt());
            m.put("lastCheckAt", w.getLastCheckAt());

            // 附带该区域同类型的解译概况（前端列表直接展示，不用再单独请求）
            List<Extraction> history = historyOf(w.getSignature(), w.getClassType());
            m.put("periodCount", history.size());
            if (!history.isEmpty()) {
                Extraction latest = history.get(history.size() - 1);
                m.put("latestDate", latest.getAcquisitionDate() == null
                        ? null : latest.getAcquisitionDate().toString());
                m.put("latestAreaHa", latest.getExtractAreaHa());
                m.put("latestCoveragePct", latest.getCoveragePct());
            }
            out.add(m);
        }
        return ApiResponse.ok(out);
    }

    public record CreateReq(Long projectId, String name, List<List<Double>> aoi,
                            String classType) {}

    /** 新建关注区：AOI 指纹与解译记录同算法，才能匹配上后续的解译结果 */
    @PostMapping
    public ApiResponse<AoiWatch> create(@RequestBody CreateReq req, Authentication auth) {
        guard.require(auth, "action:extract-manage");
        if (req.projectId() == null) {
            throw BizException.badRequest("项目不能为空");
        }
        guard.requireAccess(req.projectId(), auth);
        if (req.aoi() == null || req.aoi().size() < 3) {
            throw BizException.badRequest("AOI 至少需要 3 个顶点");
        }
        String aoiJson;
        try {
            aoiJson = new com.fasterxml.jackson.databind.ObjectMapper()
                    .writeValueAsString(req.aoi());
        } catch (Exception e) {
            throw BizException.badRequest("AOI 序列化失败");
        }
        String sig = ExtractionService.aoiSignature(aoiJson);
        String name = (req.name() == null || req.name().isBlank())
                ? "关注区-" + System.currentTimeMillis() : req.name();

        AoiWatch w = new AoiWatch(req.projectId(), auth.getName(), name, aoiJson, sig,
                req.classType() == null || req.classType().isBlank()
                        ? "VEGETATION" : req.classType());
        return ApiResponse.ok(repo.save(w));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(@PathVariable long id, Authentication auth) {
        guard.require(auth, "action:extract-manage");
        AoiWatch w = repo.findById(id).orElseThrow(() -> BizException.notFound("关注区不存在"));
        guard.requireAccess(w.getProjectId(), auth);
        repo.deleteById(id);
        return ApiResponse.ok(null);
    }

    /**
     * 检查关注区的变化：取该 AOI 同地物类型的最近两期解译结果做对比。
     *
     * 判定规则（与变化分析口径一致）：
     * - 期数 < 2 → insufficient，不编造结论
     * - 面积变化率 ≥ 5% → 提示「显著变化」，并在 message 里说明方向
     */
    @PostMapping("/{id}/check")
    public ApiResponse<Map<String, Object>> check(@PathVariable long id, Authentication auth) {
        guard.requireAccess(repo.findById(id)
                .orElseThrow(() -> BizException.notFound("关注区不存在")).getProjectId(), auth);
        AoiWatch w = repo.findById(id).orElseThrow(() -> BizException.notFound("关注区不存在"));

        List<Extraction> history = historyOf(w.getSignature(), w.getClassType());
        Map<String, Object> m = new HashMap<>();
        m.put("id", w.getId());
        m.put("name", w.getName());
        m.put("classType", w.getClassType());
        m.put("periodCount", history.size());

        if (history.size() < 2) {
            m.put("insufficient", true);
            m.put("message", "该关注区解译记录不足 2 期，暂无法判断变化趋势。"
                    + "请对不同日期的影像各解译一次后重试。");
            w.setLastCheckAt(LocalDateTime.now());
            repo.save(w);
            return ApiResponse.ok(m);
        }

        Extraction prev = history.get(history.size() - 2);
        Extraction last = history.get(history.size() - 1);
        double prevArea = prev.getExtractAreaHa() == null ? 0 : prev.getExtractAreaHa();
        double lastArea = last.getExtractAreaHa() == null ? 0 : last.getExtractAreaHa();
        double delta = lastArea - prevArea;
        double pct = prevArea > 0 ? delta / prevArea * 100.0 : 0;

        m.put("insufficient", false);
        m.put("prevDate", prev.getAcquisitionDate() == null ? null : prev.getAcquisitionDate().toString());
        m.put("lastDate", last.getAcquisitionDate() == null ? null : last.getAcquisitionDate().toString());
        m.put("prevAreaHa", round2(prevArea));
        m.put("lastAreaHa", round2(lastArea));
        m.put("deltaHa", round2(delta));
        m.put("deltaPct", round2(pct));

        boolean significant = Math.abs(pct) >= 5.0;
        m.put("significant", significant);
        if (!significant) {
            m.put("message", "面积变化 " + round2(pct) + "%，在正常波动范围内。");
        } else if (delta > 0) {
            m.put("message", "面积增长 " + round2(pct) + "%，建议核查是否存在新的扰动。");
        } else {
            m.put("message", "面积减少 " + round2(Math.abs(pct)) + "%，可能为复绿或水体扩张。");
        }

        // 快照落库，便于下次比较与列表展示
        w.setLastCheckAreaHa(lastArea);
        w.setLastCheckDate(last.getAcquisitionDate() == null
                ? null : last.getAcquisitionDate().toString());
        w.setLastCheckAt(LocalDateTime.now());
        repo.save(w);
        return ApiResponse.ok(m);
    }

    /** 取该指纹下指定地物类型的历史解译，按影像日期升序 */
    private List<Extraction> historyOf(String signature, String classType) {
        if (signature == null || signature.isBlank()) {
            return new ArrayList<>();
        }
        List<Extraction> all = extractionRepo.findByAoiSignatureOrderByAcquisitionDateAsc(signature);
        List<Extraction> out = new ArrayList<>();
        for (Extraction e : all) {
            if (classType == null || classType.equalsIgnoreCase(e.getClassType())) {
                out.add(e);
            }
        }
        return out;
    }

    private static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
