package com.ganfeng.rs.user;

import com.ganfeng.rs.auth.AuthDtos;
import com.ganfeng.rs.auth.UserAccount;
import com.ganfeng.rs.auth.UserStore;
import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.PermissionGuard;
import jakarta.validation.Valid;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 用户中心
 * 完整 CRUD 需要 action:user-manage；/options（用户名+姓名）全员开放——项目成员分配等场景用
 */
@RestController
@RequestMapping("/api/users")
public class UserAdminController {

    private final UserStore userStore;
    private final PermissionGuard guard;

    public UserAdminController(UserStore userStore, PermissionGuard guard) {
        this.userStore = userStore;
        this.guard = guard;
    }

    /** 下拉选项：只暴露用户名与姓名 */
    @GetMapping("/options")
    public ApiResponse<List<Map<String, String>>> options() {
        return ApiResponse.ok(userStore.list().stream()
                .map(u -> Map.of("username", u.getUsername(), "displayName", u.getDisplayName()))
                .toList());
    }

    @GetMapping
    public ApiResponse<List<Map<String, Object>>> list(Authentication auth) {
        guard.require(auth, "action:user-manage");
        return ApiResponse.ok(userStore.list().stream().map(this::toView).toList());
    }

    @PostMapping
    public ApiResponse<Map<String, Object>> create(@Valid @RequestBody AuthDtos.CreateUserRequest req,
                                                   Authentication auth) {
        guard.require(auth, "action:user-manage");
        UserAccount u = userStore.create(req.username(), req.displayName(), req.password(),
                req.phone() == null ? "" : req.phone(), req.role());
        return ApiResponse.ok(toView(u));
    }

    @PutMapping("/{username}")
    public ApiResponse<Map<String, Object>> update(@PathVariable String username,
                                                   @Valid @RequestBody AuthDtos.UpdateUserRequest req,
                                                   Authentication auth) {
        guard.require(auth, "action:user-manage");
        UserAccount u = userStore.update(username, req.displayName(),
                req.phone() == null ? "" : req.phone(), req.role(), req.status(), req.newPassword());
        return ApiResponse.ok(toView(u));
    }

    @DeleteMapping("/{username}")
    public ApiResponse<Void> delete(@PathVariable String username, Authentication auth) {
        guard.require(auth, "action:user-manage");
        userStore.delete(username);
        return ApiResponse.ok(null);
    }

    private Map<String, Object> toView(UserAccount u) {
        return Map.of(
                "username", u.getUsername(),
                "displayName", u.getDisplayName(),
                "role", u.getRole(),
                "phone", u.getPhone(),
                "status", u.getStatus()
        );
    }
}
