package com.ganfeng.rs.extraction;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.PermissionGuard;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 在线提取控制器
 *
 * 提取已改为**真实链路**：选影像（imageryId）+ 圈 AOI + 选地物类型
 * → 提交 inference 异步计算 → 回调落库（见 InferenceCallbackController）。
 * 前端用返回的 taskId 轮询 /api/extractions。
 */
@RestController
@RequestMapping("/api/extractions")
public class ExtractionController {

    private final ExtractionService service;
    private final PermissionGuard guard;
    private final com.ganfeng.rs.audit.AuditLogService auditLogService;

    public ExtractionController(ExtractionService service, PermissionGuard guard,
                                com.ganfeng.rs.audit.AuditLogService auditLogService) {
        this.service = service;
        this.guard = guard;
        this.auditLogService = auditLogService;
    }

    private boolean isAdmin(Authentication auth) {
        return guard.roleCodesOf(auth).contains("ADMIN");
    }

    /** 提交解译请求：imageryId 必填（影像来自影像库，不再凭空造数据）
     *  satellite 可选：上传影像需指定数据源（GF2/GF7）以决定波段映射 */
    public record SubmitRequest(
            @NotNull(message = "项目不能为空") Long projectId,
            @NotNull(message = "请选择影像") Long imageryId,
            String name,
            @NotBlank(message = "提取类型不能为空") String classType,
            @NotNull(message = "AOI 不能为空") List<List<Double>> aoi,
            String satellite
    ) {}

    @GetMapping
    public ApiResponse<List<Extraction>> list(@RequestParam(required = false) Long projectId,
                                              @RequestParam(required = false) String method,
                                              Authentication auth) {
        List<Extraction> all = service.list(projectId, auth.getName(), isAdmin(auth));
        // method 过滤：叠加分析要区分「监督分类结果」与「指数提取结果」
        if (method != null && !method.isBlank()) {
            all = all.stream()
                    .filter(e -> method.equalsIgnoreCase(e.getMethod() == null ? "INDEX" : e.getMethod()))
                    .toList();
        }
        return ApiResponse.ok(all);
    }

    @GetMapping("/{id}")
    public ApiResponse<Extraction> get(@PathVariable long id, Authentication auth) {
        return ApiResponse.ok(service.get(id, auth.getName(), isAdmin(auth)));
    }

    /** 提交真实解译任务，返回 inference 的 taskId 供轮询 */
    @PostMapping("/submit")
    public ApiResponse<Map<String, Object>> submit(@Valid @RequestBody SubmitRequest req,
                                                    Authentication auth) {
        guard.require(auth, "action:extract-manage");
        // 只能在自己可见的项目下发起解译
        guard.requireAccess(req.projectId(), auth.getName(), isAdmin(auth));
        String taskId = service.submit(req.projectId(), req.imageryId(), req.name(),
                req.classType(), req.aoi(), auth.getName(), req.satellite());
        return ApiResponse.ok(Map.of("taskId", taskId, "status", "PENDING"));
    }

    /** 在线 Sentinel-2 直接解译请求（遥感提取页，无需本地影像） */
    public record OnlineSubmitRequest(
            @NotNull(message = "项目不能为空") Long projectId,
            String name,
            @NotBlank(message = "提取类型不能为空") String classType,
            @NotNull(message = "AOI 不能为空") List<List<Double>> aoi,
            @NotBlank(message = "开始日期不能为空") String startDate,
            @NotBlank(message = "结束日期不能为空") String endDate,
            double maxCloud,
            Double threshold,
            int minAreaPx
    ) {}

    /** 提交在线解译：AWS Sentinel-2 在线拉景 + 指数 + 矢量，异步回调落库 */
    @PostMapping("/submit-online")
    public ApiResponse<Map<String, Object>> submitOnline(
            @Valid @RequestBody OnlineSubmitRequest req, Authentication auth) {
        guard.require(auth, "action:extract-manage");
        guard.requireAccess(req.projectId(), auth.getName(), isAdmin(auth));
        String taskId = service.submitOnline(req.projectId(), req.name(), req.classType(),
                req.aoi(), req.startDate(), req.endDate(), req.maxCloud(),
                req.threshold(), req.minAreaPx(), auth.getName());
        return ApiResponse.ok(Map.of("taskId", taskId, "status", "PENDING"));
    }

    /** 保存前端已算好的解译结果（遥感提取页直接落库，不再重算） */
    public record SaveRequest(
            @NotNull(message = "项目不能为空") Long projectId,
            String name,
            @NotBlank(message = "提取类型不能为空") String classType,
            List<List<List<Double>>> features,
            @NotBlank(message = "AOI 不能为空") String aoiJson,
            double coveragePct,
            double aoiAreaHa,
            String acquisitionDate,
            String satellite,
            /* INDEX 指数阈值（默认）/ SUPERVISED 监督分类 / FUSION 融合 */
            String method,
            String accuracyJson
    ) {}

    /** 直接保存解译结果（进 extractions 表，供时序/分析/权限使用） */
    @PostMapping("/save")
    public ApiResponse<Extraction> save(@Valid @RequestBody SaveRequest req,
                                         Authentication auth) {
        guard.require(auth, "action:extract-manage");
        guard.requireAccess(req.projectId(), auth.getName(), isAdmin(auth));
        Extraction e = service.save(req.projectId(), req.name(), req.classType(),
                req.features(), req.aoiJson(), req.coveragePct(), req.aoiAreaHa(),
                req.acquisitionDate(), req.satellite(), auth.getName(),
                req.method(), req.accuracyJson());
        // 审计：保存解译结果（含地物类型与覆盖率，便于回溯）
        auditLogService.record(auth.getName(), "EXTRACT_SAVE", "EXTRACTION", String.valueOf(e.getId()),
                String.format("保存解译结果「%s」类型=%s 覆盖率=%.2f%%",
                        req.name(), req.classType(), req.coveragePct()), null);
        return ApiResponse.ok(e);
    }

    /** 删除到回收站（软删除，可还原） */
    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(@PathVariable long id, Authentication auth) {
        guard.require(auth, "action:extract-manage");
        service.get(id, auth.getName(), isAdmin(auth));
        service.delete(id, auth.getName());
        auditLogService.record(auth.getName(), "DELETE", "EXTRACTION", String.valueOf(id),
                "解译记录移入回收站", null);
        return ApiResponse.ok(null);
    }

    /** 回收站列表 */
    @GetMapping("/trash")
    public ApiResponse<List<Extraction>> trash(@RequestParam(required = false) Long projectId,
                                                Authentication auth) {
        return ApiResponse.ok(service.trash(projectId, auth.getName(), isAdmin(auth)));
    }

    /** 从回收站还原 */
    @PostMapping("/{id}/restore")
    public ApiResponse<Extraction> restore(@PathVariable long id, Authentication auth) {
        guard.require(auth, "action:extract-manage");
        service.get(id, auth.getName(), isAdmin(auth));
        Extraction e = service.restore(id);
        auditLogService.record(auth.getName(), "RESTORE", "EXTRACTION", String.valueOf(id),
                "从回收站还原解译记录", null);
        return ApiResponse.ok(e);
    }

    /** 彻底删除（不可恢复，仅限回收站内记录） */
    @DeleteMapping("/{id}/purge")
    public ApiResponse<Void> purge(@PathVariable long id, Authentication auth) {
        guard.require(auth, "action:extract-manage");
        service.get(id, auth.getName(), isAdmin(auth));
        service.purge(id);
        auditLogService.record(auth.getName(), "PURGE", "EXTRACTION", String.valueOf(id),
                "彻底删除解译记录", null);
        return ApiResponse.ok(null);
    }

    /** 查询某影像关联的解译记录数（删影像前提示用） */
    @GetMapping("/count-by-imagery")
    public ApiResponse<Long> countByImagery(@RequestParam Long imageryId) {
        return ApiResponse.ok(service.countByImagery(imageryId));
    }

    /** 影像删除时级联把关联解译记录放入回收站 */
    @PostMapping("/trash-by-imagery")
    public ApiResponse<Integer> trashByImagery(@RequestParam Long imageryId, Authentication auth) {
        guard.require(auth, "action:extract-manage");
        int n = service.trashByImagery(imageryId, auth.getName());
        auditLogService.record(auth.getName(), "DELETE", "IMAGERY", String.valueOf(imageryId),
                "影像关联解译记录级联移入回收站（" + n + " 条）", null);
        return ApiResponse.ok(n);
    }
}