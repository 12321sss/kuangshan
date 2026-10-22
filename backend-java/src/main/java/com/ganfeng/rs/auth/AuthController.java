package com.ganfeng.rs.auth;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.config.JwtService;
import jakarta.validation.Valid;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

/**
 * 认证控制器：只负责请求解析 / Cookie 写入 / 响应格式化，业务在 AuthService
 * 刷新令牌走 HttpOnly Cookie；另设一个可读的 rs_session 标记 Cookie（无敏感内容），
 * 让前端知道"有没有会话"，没有就跳过刷新探测，避免浏览器控制台刷 401
 */
@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private static final String REFRESH_COOKIE = "refresh_token";
    private static final String SESSION_MARKER = "rs_session";

    private final AuthService authService;
    private final JwtService jwtService;
    private final com.ganfeng.rs.audit.AuditLogService auditLogService;

    public AuthController(AuthService authService, JwtService jwtService,
                          com.ganfeng.rs.audit.AuditLogService auditLogService) {
        this.authService = authService;
        this.jwtService = jwtService;
        this.auditLogService = auditLogService;
    }

    @PostMapping("/login")
    public ResponseEntity<ApiResponse<AuthDtos.TokenResponse>> login(
            @Valid @RequestBody AuthDtos.LoginRequest req,
            jakarta.servlet.http.HttpServletRequest httpReq) {
        ResponseEntity<ApiResponse<AuthDtos.TokenResponse>> resp =
                tokenResponse(authService.login(req.username(), req.password()));
        // 登录成功才记审计（失败不记，避免被暴力尝试撑爆日志）
        auditLogService.record(req.username(), "LOGIN", "AUTH", req.username(),
                "用户登录成功", clientIp(httpReq));
        return resp;
    }

    @PostMapping("/refresh")
    public ResponseEntity<ApiResponse<AuthDtos.TokenResponse>> refresh(
            @CookieValue(name = REFRESH_COOKIE, required = false) String refreshToken) {
        try {
            return tokenResponse(authService.refresh(refreshToken));
        } catch (Exception e) {
            // 刷新失败（令牌缺失/过期/被撤销）：必须同时清掉会话标记 rs_session。
            // 否则前端每次页面加载都会看到标记还在，于是再探测一次 refresh，
            // 控制台就会反复出现 "api/auth/refresh 401"。清掉标记后前端直接走登录页。
            return ResponseEntity.status(401)
                    .header(HttpHeaders.SET_COOKIE, clearCookie(SESSION_MARKER).toString())
                    .header(HttpHeaders.SET_COOKIE, clearCookie(REFRESH_COOKIE).toString())
                    .body(ApiResponse.error(401, "登录已过期，请重新登录"));
        }
    }

    @PostMapping("/logout")
    public ResponseEntity<ApiResponse<Void>> logout(
            @CookieValue(name = REFRESH_COOKIE, required = false) String refreshToken) {
        authService.logout(refreshToken);
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, clearCookie(REFRESH_COOKIE).toString())
                .header(HttpHeaders.SET_COOKIE, clearCookie(SESSION_MARKER).toString())
                .body(ApiResponse.ok(null));
    }

    @GetMapping("/me")
    public ApiResponse<AuthDtos.UserInfo> me(Authentication authentication) {
        return ApiResponse.ok(authService.currentUser(authentication.getName()));
    }

    // ---- 私有工具 ----

    /** 取客户端 IP：优先 X-Forwarded-For（经代理时），否则取直连地址 */
    private static String clientIp(jakarta.servlet.http.HttpServletRequest req) {
        String xff = req.getHeader("X-Forwarded-For");
        if (xff != null && !xff.isBlank()) {
            return xff.split(",")[0].trim();
        }
        return req.getRemoteAddr();
    }

    private ResponseEntity<ApiResponse<AuthDtos.TokenResponse>> tokenResponse(AuthService.LoginResult result) {
        AuthDtos.TokenResponse body = new AuthDtos.TokenResponse(
                result.accessToken(),
                jwtService.getAccessTtlMinutes(), // 访问令牌有效期（分钟），供前端参考
                result.user());
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, refreshCookie(result.refreshToken()).toString())
                .header(HttpHeaders.SET_COOKIE, sessionMarkerCookie().toString())
                .body(ApiResponse.ok(body));
    }

    private ResponseCookie refreshCookie(String refreshToken) {
        return ResponseCookie.from(REFRESH_COOKIE, refreshToken)
                .httpOnly(true)
                .sameSite("Lax")
                .path("/api/auth")
                .maxAge(jwtService.getRefreshTtlSeconds())
                .build();
    }

    /** 会话标记：非 HttpOnly、无敏感内容，仅供前端判断是否尝试静默刷新 */
    private ResponseCookie sessionMarkerCookie() {
        return ResponseCookie.from(SESSION_MARKER, "1")
                .httpOnly(false)
                .sameSite("Lax")
                .path("/")
                .maxAge(jwtService.getRefreshTtlSeconds())
                .build();
    }

    private ResponseCookie clearCookie(String name) {
        return ResponseCookie.from(name, "")
                .httpOnly(REFRESH_COOKIE.equals(name))
                .sameSite("Lax")
                .path(REFRESH_COOKIE.equals(name) ? "/api/auth" : "/")
                .maxAge(0)
                .build();
    }
}
