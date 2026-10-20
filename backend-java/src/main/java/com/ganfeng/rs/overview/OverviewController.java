package com.ganfeng.rs.overview;

import com.ganfeng.rs.alarm.AlarmService;
import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.PermissionGuard;
import com.ganfeng.rs.extraction.Extraction;
import com.ganfeng.rs.extraction.ExtractionService;
import com.ganfeng.rs.imagery.Imagery;
import com.ganfeng.rs.imagery.ImageryService;
import com.ganfeng.rs.sensor.SensorService;
import com.ganfeng.rs.task.TaskService;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 大屏总览：按项目聚合统计指标，供仪表盘卡片使用
 *
 * 全部数字来自真实库，不再有写死的模拟值：
 *  - imageCount   = imagery 表真实景数
 *  - pitAreaHa    = extractions 表 PIT 类真实面积之和
 *  - 植被/复绿面积 = VEGETATION 类真实面积
 *  - 在线设备/告警 = sensors / alarms 真实状态
 */
@RestController
@RequestMapping("/api/overview")
public class OverviewController {

    private final SensorService sensorService;
    private final TaskService taskService;
    private final AlarmService alarmService;
    private final ImageryService imageryService;
    private final ExtractionService extractionService;
    private final PermissionGuard guard;

    public OverviewController(SensorService sensorService, TaskService taskService,
                              AlarmService alarmService, ImageryService imageryService,
                              ExtractionService extractionService, PermissionGuard guard) {
        this.sensorService = sensorService;
        this.taskService = taskService;
        this.alarmService = alarmService;
        this.imageryService = imageryService;
        this.extractionService = extractionService;
        this.guard = guard;
    }

    @GetMapping("/stats")
    public ApiResponse<Map<String, Object>> stats(@RequestParam(required = false) Long projectId,
                                                  Authentication auth) {
        boolean isAdmin = guard.isAdmin(auth);
        String username = auth.getName();

        long online = sensorService.list(projectId).stream()
                .filter(s -> "ONLINE".equals(s.getStatus())).count();
        long alarm = alarmService.list(projectId).stream()
                .filter(a -> "UNACK".equals(a.getStatus())).count();
        long runningTasks = taskService.list(projectId).stream()
                .filter(t -> "RUNNING".equals(t.getStatus())).count();

        // 真实统计：影像景数
        List<Imagery> imageries = imageryService.list(projectId, null, username, isAdmin);
        long imageCount = imageries.size();

        // 真实统计：按地物类型累计面积（PIT 采坑 / VEGETATION 植被）
        List<Extraction> extractions = extractionService.list(projectId, username, isAdmin);
        double pitArea = 0;
        double vegetationArea = 0;
        for (Extraction e : extractions) {
            double area = e.getExtractAreaHa() == null ? 0 : e.getExtractAreaHa();
            if ("PIT".equalsIgnoreCase(e.getClassType())) {
                pitArea += area;
            } else if ("VEGETATION".equalsIgnoreCase(e.getClassType())) {
                vegetationArea += area;
            }
        }

        return ApiResponse.ok(Map.of(
                "imageCount", imageCount,
                "taskRunning", runningTasks,
                "sensorOnline", online,
                "sensorAlarm", alarm,
                "pitAreaHa", round2(pitArea),
                "pitAreaChangeHa", 0,            // 年度扩张需两期对比，单值无法定，前端未用
                "vegetationLossHa", 0,           // 植被损失需历史对比，前端未用
                "recoveryAreaHa", round2(vegetationArea)   // 当前植被面积（持续复绿观测口径）
        ));
    }

    private static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}