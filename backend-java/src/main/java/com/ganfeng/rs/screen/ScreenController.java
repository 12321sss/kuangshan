package com.ganfeng.rs.screen;

import com.ganfeng.rs.alarm.AlarmService;
import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.project.Project;
import com.ganfeng.rs.project.ProjectService;
import com.ganfeng.rs.sensor.SensorService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * GIS 大屏聚合接口：一个接口给齐大屏左右面板所需的全部统计
 * 项目名/地址随当前选中项目动态返回（数据中台项目隔离）
 */
@RestController
@RequestMapping("/api/screen")
public class ScreenController {

    private final SensorService sensorService;
    private final AlarmService alarmService;
    private final ProjectService projectService;

    public ScreenController(SensorService sensorService, AlarmService alarmService,
                            ProjectService projectService) {
        this.sensorService = sensorService;
        this.alarmService = alarmService;
        this.projectService = projectService;
    }

    @GetMapping("/summary")
    public ApiResponse<Map<String, Object>> summary(@RequestParam long projectId) {
        Project project = projectService.get(projectId);
        long online = sensorService.list(projectId).stream().filter(s -> "ONLINE".equals(s.getStatus())).count();
        long total = sensorService.list(projectId).size();
        var alarms = alarmService.list(projectId);
        long todayAlarms = alarms.stream()
                .filter(a -> a.getCreatedAt().toLocalDate().equals(java.time.LocalDate.now()))
                .count();

        // 键值对超过 10 组，必须用 Map.ofEntries（Map.of 最多 10 组）
        return ApiResponse.ok(Map.ofEntries(
                Map.entry("projectName", project.getName()),
                Map.entry("orgName", "矿山运营单位（演示）"),
                Map.entry("monitorSubject", "露天采坑 / 排土场 / 边坡"),
                Map.entry("address", project.getRegion() == null ? "" : project.getRegion()),
                Map.entry("contact", "0797-0000000"),
                Map.entry("safeDays", 186),
                Map.entry("stationCount", total),
                Map.entry("todayAlarms", todayAlarms),
                Map.entry("deviceOnline", online),
                Map.entry("deviceTotal", total),
                Map.entry("alarmRed", alarms.stream().filter(a -> "RED".equals(a.getLevel())).count()),
                Map.entry("alarmOrange", alarms.stream().filter(a -> "ORANGE".equals(a.getLevel())).count()),
                Map.entry("alarmYellow", alarms.stream().filter(a -> "YELLOW".equals(a.getLevel())).count()),
                Map.entry("alarmBlue", alarms.stream().filter(a -> "BLUE".equals(a.getLevel())).count())
        ));
    }
}
