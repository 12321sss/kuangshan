package com.ganfeng.rs.sensor;

import com.ganfeng.rs.common.ApiResponse;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

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

    public SensorController(SensorService sensorService) {
        this.sensorService = sensorService;
    }

    @GetMapping
    public ApiResponse<List<Sensor>> list(@RequestParam(required = false) Long projectId) {
        return ApiResponse.ok(sensorService.list(projectId));
    }

    @GetMapping("/{id}/data")
    public ApiResponse<List<SensorDataPoint>> data(@PathVariable String id,
                                                   @RequestParam(defaultValue = "24") int hours) {
        return ApiResponse.ok(sensorService.history(id, hours));
    }

    /** GNSS 位移多分量（X/Y/Z/合位移） */
    @GetMapping("/{id}/displacement")
    public ApiResponse<Map<String, List<SensorDataPoint>>> displacement(@PathVariable String id,
                                                                        @RequestParam(defaultValue = "24") int hours) {
        return ApiResponse.ok(sensorService.displacement(id, hours));
    }

    /**
     * 传感器历史数据导出 CSV（客户要拿数据走）。
     * 返回文件流，浏览器直接下载。
     */
    @GetMapping("/{id}/export")
    public ResponseEntity<byte[]> exportCsv(@PathVariable String id,
                                            @RequestParam(defaultValue = "168") int hours) {
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
