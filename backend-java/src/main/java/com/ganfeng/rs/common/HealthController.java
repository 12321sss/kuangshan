package com.ganfeng.rs.common;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.Map;

/**
 * 简单存活探针（/actuator/health 之外的轻量端点）
 */
@RestController
public class HealthController {

    @GetMapping("/health")
    public Map<String, Object> health() {
        return Map.of(
                "status", "UP",
                "service", "rs-platform-backend",
                "time", LocalDateTime.now().toString()
        );
    }
}
