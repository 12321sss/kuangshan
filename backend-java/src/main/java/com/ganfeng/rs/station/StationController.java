package com.ganfeng.rs.station;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.PermissionGuard;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 站点控制器：按项目过滤；增删改需要 action:station-manage
 */
@RestController
@RequestMapping("/api/stations")
public class StationController {

    private final StationService service;
    private final PermissionGuard guard;

    public StationController(StationService service, PermissionGuard guard) {
        this.service = service;
        this.guard = guard;
    }

    @GetMapping
    public ApiResponse<List<Station>> list(@RequestParam(required = false) Long projectId) {
        return ApiResponse.ok(service.list(projectId));
    }

    @PostMapping
    public ApiResponse<Station> create(@RequestBody Station req, Authentication auth) {
        guard.require(auth, "action:station-manage");
        return ApiResponse.ok(service.create(req));
    }

    @PutMapping("/{id}")
    public ApiResponse<Station> update(@PathVariable String id, @RequestBody Station req,
                                       Authentication auth) {
        guard.require(auth, "action:station-manage");
        return ApiResponse.ok(service.update(id, req));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(@PathVariable String id, Authentication auth) {
        guard.require(auth, "action:station-manage");
        service.delete(id);
        return ApiResponse.ok(null);
    }
}
