package com.ganfeng.rs.auth;

import com.ganfeng.rs.common.BizException;
import com.ganfeng.rs.config.JwtService;
import com.ganfeng.rs.role.RoleStore;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

/**
 * 认证服务：承载登录校验与令牌签发的业务规则，不依赖 HTTP 类型
 */
@Service
public class AuthService {

    private final UserStore userStore;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;
    private final RoleStore roleStore;

    public AuthService(UserStore userStore, PasswordEncoder passwordEncoder,
                       JwtService jwtService, RoleStore roleStore) {
        this.userStore = userStore;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
        this.roleStore = roleStore;
    }

    /** 登录：校验用户名密码与账号状态，返回访问令牌 + 新刷新令牌 */
    public LoginResult login(String username, String rawPassword) {
        UserAccount user = userStore.findByUsername(username)
                .filter(u -> passwordEncoder.matches(rawPassword, u.getPasswordHash()))
                .orElseThrow(() -> BizException.unauthorized("用户名或密码错误"));
        requireEnabled(user);
        return issueTokens(user);
    }

    /** 刷新：旋转旧刷新令牌，签发新令牌对 */
    public LoginResult refresh(String refreshToken) {
        String username = jwtService.rotateRefreshToken(refreshToken);
        UserAccount user = userStore.findByUsername(username)
                .orElseThrow(() -> BizException.unauthorized("账号不存在或已被禁用"));
        requireEnabled(user);
        return issueTokens(user);
    }

    public void logout(String refreshToken) {
        jwtService.revokeRefreshToken(refreshToken);
    }

    public AuthDtos.UserInfo currentUser(String username) {
        UserAccount user = userStore.findByUsername(username)
                .orElseThrow(() -> BizException.unauthorized("账号不存在或已被禁用"));
        return toUserInfo(user);
    }

    private void requireEnabled(UserAccount user) {
        if (!"ENABLED".equals(user.getStatus())) {
            throw BizException.unauthorized("账号已被禁用，请联系管理员");
        }
    }

    private AuthDtos.UserInfo toUserInfo(UserAccount user) {
        // 权限从角色实时解析：管理员改了角色权限，用户下次操作即生效
        return new AuthDtos.UserInfo(user.getUsername(), user.getDisplayName(), user.getRole(), user.getPhone(),
                roleStore.pagePermsOf(user.getRole()), roleStore.actionPermsOf(user.getRole()));
    }

    private LoginResult issueTokens(UserAccount user) {
        String accessToken = jwtService.createAccessToken(user.getUsername(), user.getRole());
        String refreshToken = jwtService.createRefreshToken(user.getUsername());
        return new LoginResult(accessToken, refreshToken, toUserInfo(user));
    }

    /** 服务层返回值：令牌对与用户信息，由控制器决定如何写入响应/Cookie */
    public record LoginResult(String accessToken, String refreshToken, AuthDtos.UserInfo user) {}
}
