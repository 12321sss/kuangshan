package com.ganfeng.rs.audit;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.PermissionGuard;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 操作日志查询：管理员看全量，普通用户只看自己的操作记录。
 */
@RestController
@RequestMapping("/api/audit-logs")
public class AuditLogController {

    private final AuditLogService service;
    private final PermissionGuard guard;

    public AuditLogController(AuditLogService service, PermissionGuard guard) {
        this.service = service;
        this.guard = guard;
    }

    @GetMapping
    public ApiResponse<List<AuditLog>> list(@RequestParam(defaultValue = "200") int limit,
                                            Authentication auth) {
        boolean admin = guard.roleCodesOf(auth).contains("ADMIN");
        return ApiResponse.ok(service.list(auth.getName(), admin, limit));
    }
}
