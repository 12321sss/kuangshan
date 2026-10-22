package com.ganfeng.rs.sensor;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.BizException;
import com.ganfeng.rs.common.PermissionGuard;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.security.core.Authentication;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

/**
 * 传感器控制器：按项目过滤（数据中台项目隔离）
 */
@RestController
@RequestMapping("/api/sensors")
public class SensorController {

    private final SensorService sensorService;
    private final PermissionGuard guard;

    public SensorController(SensorService sensorService, PermissionGuard guard) {
        this.sensorService = sensorService;
        this.guard = guard;
    }

    /**
     * 按传感器 id 校验项目访问权。
     *
     * 修复：此前本控制器 4 个端点都没有权限校验，任何登录用户只要知道传感器 id
     * 就能读到其他项目的位移/雨量数据并导出 CSV——属于跨项目越权。
     */
    private void requireSensorAccess(String sensorId, Authentication auth) {
        Sensor sensor = sensorService.get(sensorId);
        if (sensor == null) {
            throw BizException.notFound("传感器不存在: " + sensorId);
        }
        if (sensor.getProjectId() != null) {
            guard.requireAccess(sensor.getProjectId(), auth);
        }
    }

    @GetMapping
    public ApiResponse<List<Sensor>> list(@RequestParam Long projectId, Authentication auth) {
        // projectId 必填并校验成员身份：传感器数据按项目隔离，不能跨项目读
        guard.requireAccess(projectId, auth);
        return ApiResponse.ok(sensorService.list(projectId));
    }

    @GetMapping("/{id}/data")
    public ApiResponse<List<SensorDataPoint>> data(@PathVariable String id,
                                                   @RequestParam(defaultValue = "24") int hours,
                                                   Authentication auth) {
        requireSensorAccess(id, auth);
        return ApiResponse.ok(sensorService.history(id, hours));
    }

    /** GNSS 位移多分量（X/Y/Z/合位移） */
    @GetMapping("/{id}/displacement")
    public ApiResponse<Map<String, List<SensorDataPoint>>> displacement(@PathVariable String id,
                                                                        @RequestParam(defaultValue = "24") int hours,
                                                                        Authentication auth) {
        requireSensorAccess(id, auth);
        return ApiResponse.ok(sensorService.displacement(id, hours));
    }

    /**
     * 传感器历史数据导出 CSV（客户要拿数据走）。
     * 返回文件流，浏览器直接下载。
     */
    @GetMapping("/{id}/export")
    public ResponseEntity<byte[]> exportCsv(@PathVariable String id,
                                            @RequestParam(defaultValue = "168") int hours,
                                            Authentication auth) {
        requireSensorAccess(id, auth);
        List<SensorDataPoint> points = sensorService.history(id, hours);
        Sensor sensor = sensorService.get(id);

        StringBuilder sb = new StringBuilder();
        // UTF-8 BOM：Excel 打开中文不乱码
        sb.append('\uFEFF');
        sb.append("传感器编号,传感器名称,时间,数值,单位\n");
        String unit = sensor == null ? "" : nvl(sensor.getUnit());
        String name = sensor == null ? id : nvl(sensor.getName());
        for (SensorDataPoint p : points) {
            sb.append(csv(id)).append(',')
              .append(csv(name)).append(',')
              .append(csv(p.time() == null ? "" : p.time().toString())).append(',')
              .append(p.value()).append(',')
              .append(csv(unit)).append('\n');
        }

        byte[] bytes = sb.toString().getBytes(StandardCharsets.UTF_8);
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.parseMediaType("text/csv; charset=UTF-8"));
        headers.setContentDispositionFormData("attachment", "sensor-" + id + "-" + hours + "h.csv");
        return new ResponseEntity<>(bytes, headers, org.springframework.http.HttpStatus.OK);
    }

    /** CSV 字段转义：含逗号/引号/换行时加引号并转义内部引号 */
    private static String csv(String v) {
        if (v == null) return "";
        if (v.contains(",") || v.contains("\"") || v.contains("\n")) {
            return "\"" + v.replace("\"", "\"\"") + "\"";
        }
        return v;
    }

    private static String nvl(String v) { return v == null ? "" : v; }
}
