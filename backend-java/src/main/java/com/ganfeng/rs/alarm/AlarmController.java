package com.ganfeng.rs.alarm;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.PermissionGuard;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 告警控制器：查看按项目过滤全员开放；确认需要 action:alarm-ack
 */
@RestController
@RequestMapping("/api/alarms")
public class AlarmController {

    private final AlarmService service;
    private final PermissionGuard guard;

    public AlarmController(AlarmService service, PermissionGuard guard) {
        this.service = service;
        this.guard = guard;
    }

    @GetMapping
    public ApiResponse<List<Alarm>> list(@RequestParam(required = false) Long projectId) {
        return ApiResponse.ok(service.list(projectId));
    }

    @PostMapping("/{id}/ack")
    public ApiResponse<Alarm> ack(@PathVariable long id, Authentication auth) {
        guard.require(auth, "action:alarm-ack");
        return ApiResponse.ok(service.ack(id));
    }

    /** 闭环处理：认领→处理→关闭，body 含处理人 + 处理意见 */
    public record ResolveRequest(String handledBy, String handleComment) {}

    @PostMapping("/{id}/resolve")
    public ApiResponse<Alarm> resolve(@PathVariable long id, @RequestBody ResolveRequest req,
                                      Authentication auth) {
        guard.require(auth, "action:alarm-ack");
        return ApiResponse.ok(service.resolve(id, req.handledBy(), req.handleComment()));
    }
}
