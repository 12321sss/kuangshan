package com.ganfeng.rs.warning;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.PermissionGuard;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 预警规则控制器：查看全员开放；修改需要 action:rule-edit
 */
@RestController
@RequestMapping("/api/warning-rules")
public class WarningRuleController {

    private final WarningRuleService service;
    private final PermissionGuard guard;

    public WarningRuleController(WarningRuleService service, PermissionGuard guard) {
        this.service = service;
        this.guard = guard;
    }

    @GetMapping
    public ApiResponse<List<WarningRule>> list() {
        return ApiResponse.ok(service.list());
    }

    @PutMapping("/{id}")
    public ApiResponse<WarningRule> update(@PathVariable long id, @RequestBody WarningRule req,
                                           Authentication auth) {
        guard.require(auth, "action:rule-edit");
        return ApiResponse.ok(service.update(id, req));
    }
}
