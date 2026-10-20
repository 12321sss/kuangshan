package com.ganfeng.rs.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ganfeng.rs.common.ApiResponse;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.MediaType;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * 安全配置：无状态 JWT、显式 CORS 来源、规范化 401
 * CSRF：demo 阶段关闭（刷新令牌 Cookie 为 SameSite=Lax，生产前需重新评估）
 */
@Configuration
public class SecurityConfig {

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http, JwtAuthFilter jwtAuthFilter) throws Exception {
        ObjectMapper om = new ObjectMapper();
        http
            .csrf(csrf -> csrf.disable())
            .cors(cors -> cors.configurationSource(corsSource()))
            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .exceptionHandling(e -> e.authenticationEntryPoint((req, res, ex) -> {
                res.setStatus(401);
                res.setContentType(MediaType.APPLICATION_JSON_VALUE);
                res.setCharacterEncoding(StandardCharsets.UTF_8.name());
                res.getWriter().write(om.writeValueAsString(ApiResponse.error(401, "未登录或登录已过期")));
            }))
            .authorizeHttpRequests(auth -> auth
                    // 登录相关 + 探活公开
                    .requestMatchers("/api/auth/login", "/api/auth/refresh", "/api/auth/logout",
                            "/actuator/health", "/health").permitAll()
                    // inference 服务回调入口：机器对机器调用，无登录态。
                    // 生产期应改为校验回调签名/IP 白名单，此处 demo 期先放行。
                    .requestMatchers("/api/callback/**").permitAll()
                    // 访客分享只读视图：凭随机 token 访问，无需登录（token 本身即凭证）
                    .requestMatchers("/api/share/view/**").permitAll()
                    .anyRequest().authenticated())
            .addFilterBefore(jwtAuthFilter, UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }

    /** 显式来源，禁止生产通配符；前端开发服务器端口 5173 */
    @Bean
    public CorsConfigurationSource corsSource() {
        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOrigins(List.of("http://localhost:5173", "http://127.0.0.1:5173"));
        config.setAllowedMethods(List.of("GET", "POST", "PUT", "DELETE", "OPTIONS"));
        config.setAllowedHeaders(List.of("*"));
        config.setAllowCredentials(true);
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        return source;
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
}
