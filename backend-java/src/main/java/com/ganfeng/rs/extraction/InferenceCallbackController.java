package com.ganfeng.rs.extraction;

import com.ganfeng.rs.common.ApiResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * inference 回调入口（/api/callback/task-complete）
 *
 * 独立成类而非挂在 ExtractionController 上：回调路径与业务查询路径不同，
 * 且回调是机器对机器调用（无登录态），在 SecurityConfig 里单独放行。
 *
 * 【安全】回调必须携带共享密钥 X-Inference-Token。
 * 该端点一旦裸奔，任何人 POST 一条 SUCCESS 就能往 extractions 写入任意
 * 面积/像元的假数据（实测可写入 9999 ha 假记录），演示时数据来源不可信。
 * 生产期应升级为 HMAC 签名 + 时间戳防重放；当前用共享密钥 + 数值合理性校验。
 */
@RestController
@RequestMapping("/api/callback")
public class InferenceCallbackController {

    private static final Logger log = LoggerFactory.getLogger(InferenceCallbackController.class);

    /** 回调共享密钥：需与 inference 侧 INFERENCE_CALLBACK_TOKEN 一致 */
    @Value("${INFERENCE_CALLBACK_TOKEN:rs-demo-inference-token-2026}")
    private String callbackToken;

    private final ExtractionService service;

    public InferenceCallbackController(ExtractionService service) {
        this.service = service;
    }

    @PostMapping("/task-complete")
    public ResponseEntity<ApiResponse<Map<String, Object>>> taskComplete(
            @RequestHeader(value = "X-Inference-Token", required = false) String token,
            @RequestBody Map<String, Object> payload) {

        // 密钥校验：不通过直接 401，不落任何数据
        if (token == null || !token.equals(callbackToken)) {
            log.warn("回调鉴权失败：X-Inference-Token 不匹配");
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                    .body(ApiResponse.error(401, "回调鉴权失败"));
        }

        String taskId = str(payload.get("taskId"));
        String status = str(payload.get("status"));
        String classType = str(payload.get("classType"));
        long projectId = longVal(payload.get("projectId"), 0L);
        long imageryId = longVal(payload.get("imageryId"), 0L);
        double extractHa = num(payload.get("extractAreaHa"), 0d);
        double aoiHa = num(payload.get("aoiAreaHa"), 0d);
        double coverage = num(payload.get("coveragePct"), 0d);
        int pixelCount = (int) num(payload.get("pixelCount"), 0d);
        String error = str(payload.get("error"));

        // 数值合理性校验：挡住明显异常的回调（面积非正或超合理上限、覆盖率越界）
        if ("SUCCESS".equals(status)) {
            if (extractHa <= 0 || extractHa > 1_000_000) {
                log.warn("回调数据异常被拒 taskId={} extractHa={}", taskId, extractHa);
                return ResponseEntity.ok(ApiResponse.ok(Map.of(
                        "received", false, "taskId", taskId, "reason", "提取面积超出合理范围")));
            }
            if (coverage < 0 || coverage > 100.001) {
                log.warn("回调覆盖率异常被拒 taskId={} coverage={}", taskId, coverage);
                return ResponseEntity.ok(ApiResponse.ok(Map.of(
                        "received", false, "taskId", taskId, "reason", "覆盖率越界")));
            }
            if (projectId <= 0) {
                log.warn("回调缺少项目上下文被拒 taskId={} projectId={}", taskId, projectId);
                return ResponseEntity.ok(ApiResponse.ok(Map.of(
                        "received", false, "taskId", taskId, "reason", "缺少项目上下文")));
            }
        }

        log.info("收到解译回调 taskId={} status={} classType={} area={}ha",
                taskId, status, classType, extractHa);

        if ("SUCCESS".equals(status)) {
            @SuppressWarnings("unchecked")
            List<List<List<Double>>> polygons =
                    (List<List<List<Double>>>) (List<?>) payload.get("polygons");
            // 拍摄日期由 inference 原样带回，缺失则退到当前年份
            java.time.LocalDate acq = null;
            Object acqRaw = payload.get("acquisitionDate");
            if (acqRaw != null) {
                try {
                    acq = java.time.LocalDate.parse(acqRaw.toString());
                } catch (Exception ignored) {
                    acq = null;
                }
            }
            // AOI 回写：时序播放靠它识别同一区域的不同期结果
            String aoiJson = null;
            Object aoiRaw = payload.get("aoi");
            if (aoiRaw != null) {
                try {
                    aoiJson = new com.fasterxml.jackson.databind.ObjectMapper()
                            .writeValueAsString(aoiRaw);
                } catch (Exception e) {
                    log.warn("AOI 序列化失败 taskId={}: {}", taskId, e.getMessage());
                }
            }
            service.complete(taskId, projectId, imageryId, classType, polygons,
                    pixelCount, extractHa, aoiHa, coverage,
                    str(payload.get("name")), str(payload.get("satellite")), acq, aoiJson);
            return ResponseEntity.ok(ApiResponse.ok(Map.of("received", true, "taskId", taskId)));
        }

        if ("FAILED".equals(status)) {
            log.warn("解译失败 taskId={} error={}", taskId, error);
        }
        // EMPTY（该 AOI 内无目标地物）与 FAILED 均不落库，仅回执避免无限重试
        return ResponseEntity.ok(ApiResponse.ok(Map.of("received", true, "taskId", taskId,
                "status", status == null ? "UNKNOWN" : status)));
    }

    private static String str(Object o) {
        return o == null ? null : o.toString();
    }

    /** 整型取值：用于 projectId / imageryId 等 ID 字段 */
    private static long longVal(Object o, long def) {
        if (o instanceof Number n) {
            return n.longValue();
        }
        if (o == null) {
            return def;
        }
        try {
            return (long) Double.parseDouble(o.toString());
        } catch (NumberFormatException e) {
            return def;
        }
    }

    private static double num(Object o, double def) {
        if (o instanceof Number n) {
            return n.doubleValue();
        }
        if (o == null) {
            return def;
        }
        try {
            return Double.parseDouble(o.toString());
        } catch (NumberFormatException e) {
            return def;
        }
    }
}