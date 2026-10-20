package com.ganfeng.rs.sensor;

import com.ganfeng.rs.common.BizException;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Random;

/**
 * 传感器服务：档案走 MySQL；时序曲线 demo 期为确定性生成器（接 TDengine 后替换查询实现）
 */
@Service
public class SensorService {

    private final SensorRepository repo;

    public SensorService(SensorRepository repo) {
        this.repo = repo;
    }

    public List<Sensor> list(Long projectId) {
        return projectId == null ? repo.findAll() : repo.findByProjectId(projectId);
    }

    public Sensor get(String id) {
        return repo.findById(id).orElseThrow(() -> BizException.notFound("传感器不存在: " + id));
    }

    /**
     * GNSS 位移多分量时序（demo 模拟）：X/Y/Z 三分量随机游走 + 合位移（模长）
     * 告警设备末尾持续拉升，形态符合物理直觉
     */
    public Map<String, List<SensorDataPoint>> displacement(String id, int hours) {
        Sensor s = get(id);
        int n = Math.min(Math.max(hours, 1), 168);
        Random rnd = new Random(("disp-" + id).hashCode());
        LocalDateTime start = LocalDateTime.now().truncatedTo(ChronoUnit.HOURS).minusHours(n - 1L);
        double x = 0, y = 0, z = 0;
        List<SensorDataPoint> xs = new ArrayList<>(n);
        List<SensorDataPoint> ys = new ArrayList<>(n);
        List<SensorDataPoint> zs = new ArrayList<>(n);
        List<SensorDataPoint> totals = new ArrayList<>(n);
        for (int i = 0; i < n; i++) {
            x += (rnd.nextDouble() - 0.5) * 1.2;
            y += (rnd.nextDouble() - 0.5) * 1.2;
            z += (rnd.nextDouble() - 0.5) * 0.8;
            if ("ALARM".equals(s.getStatus()) && i > n * 0.75) {
                x += 0.9;
                z += 0.6;
            }
            LocalDateTime t = start.plusHours(i);
            xs.add(new SensorDataPoint(t, round2(x)));
            ys.add(new SensorDataPoint(t, round2(y)));
            zs.add(new SensorDataPoint(t, round2(z)));
            totals.add(new SensorDataPoint(t, round2(Math.sqrt(x * x + y * y + z * z))));
        }
        return Map.of("x", xs, "y", ys, "z", zs, "total", totals);
    }

    /**
     * 生成模拟时序：以设备 id 为随机种子，保证同一设备每次查询曲线一致
     */
    public List<SensorDataPoint> history(String id, int hours) {
        Sensor s = get(id);
        int n = Math.min(Math.max(hours, 1), 168);
        Random rnd = new Random(id.hashCode());
        double base = switch (s.getType()) {
            case "DISP" -> 2.0;
            case "RAIN" -> 5.0;
            case "SOIL" -> 22.0;
            case "WATER" -> 1.0;
            default -> 10.0;
        };
        double amplitude = base * 0.4;
        List<SensorDataPoint> points = new ArrayList<>(n);
        LocalDateTime start = LocalDateTime.now().truncatedTo(ChronoUnit.HOURS).minusHours(n - 1L);
        double value = base;
        for (int i = 0; i < n; i++) {
            value += (rnd.nextDouble() - 0.5) * amplitude * 0.6 + (base - value) * 0.1;
            if ("ALARM".equals(s.getStatus()) && i > n * 0.8) {
                value += amplitude * 0.35;
            }
            points.add(new SensorDataPoint(start.plusHours(i), Math.round(value * 100.0) / 100.0));
        }
        return points;
    }

    private static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
