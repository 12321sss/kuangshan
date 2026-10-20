package com.ganfeng.rs.common;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;
import org.springframework.boot.web.client.RestTemplateBuilder;

import javax.sql.DataSource;
import java.sql.Connection;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 依赖健康检查（演示前扫一眼就知道今天能不能顺利演）
 *
 * 探测四个关键依赖：数据库 / 解译服务 / 天地图底图 / AWS STAC 影像源。
 * 每个探测独立超时、独立捕获异常，任一挂了不影响其它项返回。
 */
@RestController
@RequestMapping("/api/health")
public class HealthCheckController {

    private final DataSource dataSource;
    private final RestTemplate rest;

    @Value("${INFERENCE_BASE_URL:http://localhost:8000}")
    private String inferenceBaseUrl;

    public HealthCheckController(DataSource dataSource, RestTemplateBuilder builder) {
        this.dataSource = dataSource;
        // 超时统一 3 秒，避免健康检查本身卡住页面
        this.rest = builder
                .setConnectTimeout(Duration.ofSeconds(3))
                .setReadTimeout(Duration.ofSeconds(3))
                .build();
    }

    @GetMapping("/checks")
    public ApiResponse<Map<String, Object>> checks() {
        List<Map<String, Object>> items = new ArrayList<>();
        items.add(probe("数据库 MySQL", "数据库读写", () -> {
            try (Connection c = dataSource.getConnection()) {
                return c.isValid(2);
            }
        }));
        items.add(probe("解译服务", inferenceBaseUrl, () -> {
            ResponseEntity<String> r = rest.getForEntity(inferenceBaseUrl + "/health", String.class);
            return r.getStatusCode().is2xxSuccessful();
        }));
        items.add(probe("天地图底图", "https://t0.tianditu.gov.cn", () -> {
            ResponseEntity<String> r = rest.getForEntity(
                    "https://t0.tianditu.gov.cn/DataServer?T=img_w&x=214&y=107&l=9&tk=test",
                    String.class);
            // 天地图对无效 token 也会返回 200/403，能连通即视为可达
            return r.getStatusCode().value() < 500;
        }));
        items.add(probe("AWS STAC 影像源", "https://earth-search.aws.element84.com/v1", () -> {
            ResponseEntity<String> r = rest.getForEntity(
                    "https://earth-search.aws.element84.com/v1", String.class);
            return r.getStatusCode().is2xxSuccessful();
        }));

        long okCount = items.stream().filter(i -> Boolean.TRUE.equals(i.get("ok"))).count();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", items);
        out.put("okCount", okCount);
        out.put("total", items.size());
        out.put("allOk", okCount == items.size());
        return ApiResponse.ok(out);
    }

    /** 单个探测项：捕获异常并记录耗时 */
    private Map<String, Object> probe(String name, String target, ThrowingSupplier action) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("name", name);
        m.put("target", target);
        long start = System.currentTimeMillis();
        try {
            m.put("ok", action.get());
            m.put("error", null);
        } catch (org.springframework.web.client.HttpStatusCodeException e) {
            // 4xx 说明服务端可达（只是 token/参数不对），视为网络连通；
            // 5xx 才算服务异常（天地图对无效 token 返回 403，仍属可达）
            m.put("ok", e.getStatusCode().value() < 500);
            m.put("error", null);
        } catch (Exception e) {
            m.put("ok", false);
            m.put("error", e.getClass().getSimpleName() + ": " + e.getMessage());
        }
        m.put("latencyMs", System.currentTimeMillis() - start);
        return m;
    }

    @FunctionalInterface
    private interface ThrowingSupplier {
        boolean get() throws Exception;
    }
}
