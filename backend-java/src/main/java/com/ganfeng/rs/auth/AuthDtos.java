package com.ganfeng.rs.auth;

import jakarta.validation.constraints.NotBlank;

import java.util.List;

/**
 * 认证与用户管理相关 DTO 集合
 */
public final class AuthDtos {

    private AuthDtos() {}

    /** 登录请求 */
    public record LoginRequest(
            @NotBlank(message = "用户名不能为空") String username,
            @NotBlank(message = "密码不能为空") String password
    ) {}

    /** 登录/刷新成功响应：访问令牌 + 用户信息（刷新令牌只走 HttpOnly Cookie，不出现在 Body） */
    public record TokenResponse(String accessToken, long expiresInMinutes, UserInfo user) {}

    /** 当前用户信息：携带权限清单，前端据此渲染菜单与按钮 */
    public record UserInfo(String username, String displayName, String role, String phone,
                           List<String> pagePerms, List<String> actionPerms) {}

    /** 新建用户 */
    public record CreateUserRequest(
            @NotBlank(message = "用户名不能为空") String username,
            @NotBlank(message = "姓名不能为空") String displayName,
            @NotBlank(message = "初始密码不能为空") String password,
            String phone,
            @NotBlank(message = "角色不能为空") String role
    ) {}

    /** 编辑用户（密码留空表示不重置） */
    public record UpdateUserRequest(
            @NotBlank(message = "姓名不能为空") String displayName,
            String phone,
            @NotBlank(message = "角色不能为空") String role,
            @NotBlank(message = "状态不能为空") String status,
            String newPassword
    ) {}
}
