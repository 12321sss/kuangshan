package com.ganfeng.rs.share;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.BizException;
import com.ganfeng.rs.common.PermissionGuard;
import com.ganfeng.rs.extraction.Extraction;
import com.ganfeng.rs.extraction.ExtractionRepository;
import com.ganfeng.rs.project.Project;
import com.ganfeng.rs.project.ProjectRepository;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 访客分享链接：生成 / 列表 / 撤销（需登录）+ 只读访问（匿名）。
 *
 * 只读视图仅暴露项目名、地区、解译记录明细与汇总统计，
 * 不含任何用户、设备、角色等敏感信息。
 */
@RestController
@RequestMapping("/api/share")
public class ShareController {

    private static final SecureRandom RANDOM = new SecureRandom();

    private final ShareLinkRepository repo;
    private final ProjectRepository projectRepo;
    private final ExtractionRepository extractionRepo;
    private final PermissionGuard guard;

    public ShareController(ShareLinkRepository repo, ProjectRepository projectRepo,
                           ExtractionRepository extractionRepo, PermissionGuard guard) {
        this.repo = repo;
        this.projectRepo = projectRepo;
        this.extractionRepo = extractionRepo;
        this.guard = guard;
    }

    /** 生成分享链接（默认 7 天有效） */
    public record CreateReq(Long projectId, Integer validDays) {}

    @PostMapping
    public ApiResponse<Map<String, Object>> create(@RequestBody CreateReq req, Authentication auth) {
        if (req.projectId() == null) {
            throw BizException.badRequest("请指定要分享的工程");
        }
        Project p = projectRepo.findById(req.projectId())
                .orElseThrow(() -> BizException.notFound("工程不存在: " + req.projectId()));
        int days = req.validDays() == null || req.validDays() <= 0 ? 7 : Math.min(req.validDays(), 90);

        byte[] buf = new byte[16];
        RANDOM.nextBytes(buf);
        String token = HexFormat.of().formatHex(buf);

        ShareLink link = repo.save(new ShareLink(token, req.projectId(), auth.getName(), days));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("token", link.getToken());
        out.put("projectName", p.getName());
        out.put("expiresAt", link.getExpiresAt());
        out.put("path", "/share/" + link.getToken());
        return ApiResponse.ok(out);
    }

    /** 当前工程的分享链接列表 */
    @GetMapping
    public ApiResponse<List<ShareLink>> list(@RequestParam Long projectId, Authentication auth) {
        guard.require(auth, "page:projects");
        return ApiResponse.ok(repo.findByProjectIdOrderByCreatedAtDesc(projectId));
    }

    /** 撤销链接 */
    @DeleteMapping("/{id}")
    public ApiResponse<Void> revoke(@PathVariable long id, Authentication auth) {
        guard.require(auth, "page:projects");
        ShareLink link = repo.findById(id).orElseThrow(() -> BizException.notFound("链接不存在"));
        link.setRevoked(true);
        repo.save(link);
        return ApiResponse.ok(null);
    }

    /**
     * 只读访问（匿名）：按 token 返回项目概况 + 解译记录 + 统计。
     * 该路径在 SecurityConfig 中放行，无需登录。
     */
    @GetMapping("/view/{token}")
    public ApiResponse<Map<String, Object>> view(@PathVariable String token) {
        ShareLink link = repo.findByToken(token)
                .orElseThrow(() -> BizException.notFound("分享链接无效"));
        if (!link.isActive()) {
            throw BizException.badRequest("分享链接已过期或被撤销");
        }
        Project p = projectRepo.findById(link.getProjectId())
                .orElseThrow(() -> BizException.notFound("工程已不存在"));

        List<Extraction> all = extractionRepo.findAll().stream()
                .filter(e -> link.getProjectId().equals(e.getProjectId()))
                .toList();

        // 存量口径：每个 (地物类型 | AOI) 只取最新一次提取，避免重复提取导致面积翻倍
        Map<String, Extraction> latestPerAoi = new LinkedHashMap<>();
        Map<String, Integer> countByClass = new LinkedHashMap<>();
        List<Map<String, Object>> records = new ArrayList<>();
        for (Extraction e : all) {
            countByClass.merge(e.getClassType(), 1, Integer::sum);
            String aoiSig = (e.getAoiSignature() == null || e.getAoiSignature().isBlank())
                    ? "single-" + e.getId()
                    : e.getAoiSignature();
            String dedupKey = e.getClassType() + "|" + aoiSig;
            Extraction exist = latestPerAoi.get(dedupKey);
            // 保留拍摄日期最新的一条（先比日期，日期相同再比 id）
            if (exist == null || isNewer(e, exist)) {
                latestPerAoi.put(dedupKey, e);
            }

            Map<String, Object> r = new LinkedHashMap<>();
            r.put("name", e.getName());
            r.put("classType", e.getClassType());
            r.put("date", e.getAcquisitionDate());
            r.put("areaHa", e.getExtractAreaHa() == null ? 0 : e.getExtractAreaHa());
            r.put("coveragePct", e.getCoveragePct());
            records.add(r);
        }

        Map<String, Double> areaByClass = new LinkedHashMap<>();
        for (Extraction e : latestPerAoi.values()) {
            double area = e.getExtractAreaHa() == null ? 0 : e.getExtractAreaHa();
            areaByClass.merge(e.getClassType(), area, Double::sum);
        }

        List<Map<String, Object>> classes = new ArrayList<>();
        areaByClass.forEach((k, v) -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("classType", k);
            m.put("totalAreaHa", Math.round(v * 100) / 100.0);
            m.put("recordCount", countByClass.getOrDefault(k, 0));
            classes.add(m);
        });
        classes.sort((a, b) -> Double.compare((Double) b.get("totalAreaHa"), (Double) a.get("totalAreaHa")));

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("projectName", p.getName());
        out.put("region", p.getRegion());
        out.put("expiresAt", link.getExpiresAt());
        out.put("recordCount", records.size());
        out.put("classes", classes);
        out.put("records", records.size() > 100 ? records.subList(0, 100) : records);
        out.put("note", "本页为只读分享视图；各地物面积为该区域最近一次解译结果，同一区域重复解译不累加。"
                + "面积口径为潜在水土流失风险筛查结果。");
        return ApiResponse.ok(out);
    }

    /** 判断 a 是否比 b 更"新"：优先比拍摄日期，相同再比 id */
    private static boolean isNewer(Extraction a, Extraction b) {
        java.time.LocalDate da = a.getAcquisitionDate();
        java.time.LocalDate db = b.getAcquisitionDate();
        if (da != null && db != null && !da.equals(db)) return da.isAfter(db);
        if (da != null && db == null) return true;
        if (da == null && db != null) return false;
        return a.getId() > b.getId();
    }
}
