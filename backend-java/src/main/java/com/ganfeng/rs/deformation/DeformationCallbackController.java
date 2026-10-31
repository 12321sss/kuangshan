package com.ganfeng.rs.deformation;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.notification.NotificationService;
import com.ganfeng.rs.task.TaskService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 形变分析任务回调（/api/callback/deformation-complete）。
 *
 * inference 后台跑完形变分析后回调这里：更新任务状态 + 给发起人发站内通知。
 * 与解译回调（InferenceCallbackController）一样，机器对机器、无登录态，
 * 必须校验 X-Inference-Token；SecurityConfig 需放行本路径。
 */
@RestController
@RequestMapping("/api/callback")
public class DeformationCallbackController {

    private static final Logger log = LoggerFactory.getLogger(DeformationCallbackController.class);

    @Value("${INFERENCE_CALLBACK_TOKEN:rs-demo-inference-token-2026}")
    private String callbackToken;

    private final TaskService taskService;
    private final NotificationService notificationService;

    public DeformationCallbackController(TaskService taskService,
                                         NotificationService notificationService) {
        this.taskService = taskService;
        this.notificationService = notificationService;
    }

    @PostMapping("/deformation-complete")
    public ResponseEntity<ApiResponse<Map<String, Object>>> deformationComplete(
            @RequestHeader(value = "X-Inference-Token", required = false) String token,
            @RequestBody Map<String, Object> payload) {

        if (token == null || !token.equals(callbackToken)) {
            log.warn("形变回调鉴权失败");
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                    .body(ApiResponse.error(401, "回调鉴权失败"));
        }

        Long javaTaskId = longVal(payload.get("javaTaskId"));
        String status = str(payload.get("status"));
        String taskType = str(payload.get("taskType"));
        String userId = str(payload.get("userId"));
        String message = str(payload.get("message"));

        boolean ok = "SUCCESS".equals(status);
        if (javaTaskId != null && javaTaskId > 0) {
            taskService.updateStatus(javaTaskId, ok ? "SUCCESS" : "FAILED", ok ? 100 : 100);
        }

        // 站内通知：完成/失败都通知，点击跳回形变监测页
        if (userId != null && !userId.isBlank()) {
            String typeName = "fusion".equals(taskType) ? "升降轨联合解算" : "单轨形变趋势";
            if (ok) {
                notificationService.notify(userId, "形变分析完成",
                        typeName + "已完成，可查看速率场与趋势研判。", "DEFORMATION", "/deformation");
            } else {
                notificationService.notify(userId, "形变分析失败",
                        typeName + "执行失败：" + (message.isBlank() ? "未知错误" : message),
                        "DEFORMATION", "/deformation");
            }
        }

        return ResponseEntity.ok(ApiResponse.ok(Map.of("received", true)));
    }

    private static String str(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    private static Long longVal(Object o) {
        if (o == null) return null;
        try {
            return Long.valueOf(String.valueOf(o));
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
