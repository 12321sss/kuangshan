package com.ganfeng.rs.config;

import com.ganfeng.rs.common.BizException;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Date;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * JWT 服务：短时效访问令牌 + 服务端刷新令牌
 * demo 阶段刷新令牌存内存 Map（重启失效）；生产切换 Redis，接口不变
 */
@Service
public class JwtService {

    private final SecretKey key;
    private final long accessTtlMinutes;
    private final long refreshTtlDays;

    /** 刷新令牌服务端存储：token -> (用户名, 过期时间) */
    private final Map<String, RefreshEntry> refreshStore = new ConcurrentHashMap<>();

    private record RefreshEntry(String username, Instant expiresAt) {}

    public JwtService(@Value("${app.jwt.secret}") String secret,
                      @Value("${app.jwt.access-ttl-minutes}") long accessTtlMinutes,
                      @Value("${app.jwt.refresh-ttl-days}") long refreshTtlDays) {
        if (secret.getBytes(StandardCharsets.UTF_8).length < 32) {
            throw new IllegalStateException("JWT_SECRET 长度不足 32 字节，请检查环境变量");
        }
        this.key = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
        this.accessTtlMinutes = accessTtlMinutes;
        this.refreshTtlDays = refreshTtlDays;
    }

    public String createAccessToken(String username, String role) {
        Instant now = Instant.now();
        return Jwts.builder()
                .subject(username)
                .claim("role", role)
                .issuedAt(Date.from(now))
                .expiration(Date.from(now.plus(Duration.ofMinutes(accessTtlMinutes))))
                .signWith(key)
                .compact();
    }

    public String createRefreshToken(String username) {
        String token = UUID.randomUUID().toString().replace("-", "");
        refreshStore.put(token, new RefreshEntry(username, Instant.now().plus(Duration.ofDays(refreshTtlDays))));
        return token;
    }

    /** 校验并旋转刷新令牌：旧令牌立即作废，返回其所属用户名 */
    public String rotateRefreshToken(String token) {
        RefreshEntry entry = (token == null) ? null : refreshStore.remove(token);
        if (entry == null || entry.expiresAt().isBefore(Instant.now())) {
            throw BizException.unauthorized("登录已过期，请重新登录");
        }
        return entry.username();
    }

    public void revokeRefreshToken(String token) {
        if (token != null) {
            refreshStore.remove(token);
        }
    }

    public Claims parse(String jwt) {
        return Jwts.parser().verifyWith(key).build().parseSignedClaims(jwt).getPayload();
    }

    public long getRefreshTtlSeconds() {
        return Duration.ofDays(refreshTtlDays).toSeconds();
    }

    public long getAccessTtlMinutes() {
        return accessTtlMinutes;
    }
}
