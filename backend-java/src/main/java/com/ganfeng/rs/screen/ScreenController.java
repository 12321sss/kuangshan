package com.ganfeng.rs.screen;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ganfeng.rs.alarm.AlarmService;
import com.ganfeng.rs.boundary.AoiBoundaryRepository;
import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.extraction.Extraction;
import com.ganfeng.rs.extraction.ExtractionService;
import com.ganfeng.rs.imagery.Imagery;
import com.ganfeng.rs.imagery.ImageryService;
import com.ganfeng.rs.project.Project;
import com.ganfeng.rs.project.ProjectService;
import com.ganfeng.rs.sensor.SensorService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

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
    private final ExtractionService extractionService;
    private final ImageryService imageryService;
    private final AoiBoundaryRepository boundaryRepo;
    private final ObjectMapper mapper = new ObjectMapper();

    public ScreenController(SensorService sensorService, AlarmService alarmService,
                            ProjectService projectService,
                            ExtractionService extractionService,
                            ImageryService imageryService,
                            AoiBoundaryRepository boundaryRepo) {
        this.sensorService = sensorService;
        this.alarmService = alarmService;
        this.projectService = projectService;
        this.extractionService = extractionService;
        this.imageryService = imageryService;
        this.boundaryRepo = boundaryRepo;
    }

    /** 管理员可看全部项目，普通用户只看自己参与的 */
    private boolean isAdmin(org.springframework.security.core.Authentication auth) {
        return auth != null && auth.getAuthorities().stream()
                .anyMatch(a -> "ROLE_ADMIN".equals(a.getAuthority()));
    }

    @GetMapping("/summary")
    public ApiResponse<Map<String, Object>> summary(@RequestParam long projectId,
                                                    org.springframework.security.core.Authentication auth) {
        // 项目隔离：大屏汇总含矿区名称、联系人、告警数等敏感信息，必须校验成员身份。
        // 修复前任何登录用户传任意 projectId 就能看到别人矿区的运营数据。
        projectService.requireAccess(projectId, auth.getName(), isAdmin(auth));
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

    /**
     * 大屏遥感侧聚合：解译成果 KPI + 地物构成 + 按期时序 + 最近记录 + 分类精度
     *
     * 为什么单独一个接口：大屏 5 秒刷一次，不能让它并发打 6 个接口；
     * 一次取齐，前端只做渲染。数据量在千条量级，内存聚合足够（不引入额外 SQL）。
     */
    @GetMapping("/rs-overview")
    public ApiResponse<Map<String, Object>> rsOverview(@RequestParam long projectId,
                                                       org.springframework.security.core.Authentication auth) {
        boolean admin = isAdmin(auth);
        projectService.requireAccess(projectId, auth.getName(), admin);

        List<Extraction> records = extractionService.list(projectId, auth.getName(), admin);
        List<Imagery> imgs = imageryService.list(projectId, null, auth.getName(), admin);

        // ---- KPI ----
        double extractHa = records.stream()
                .mapToDouble(e -> e.getExtractAreaHa() == null ? 0 : e.getExtractAreaHa()).sum();
        // 影像没有存面积字段，按四至用等距近似换算（公顷），与其它模块口径一致
        double imageryHa = imgs.stream().mapToDouble(i -> {
            if (i.getWest() == null || i.getEast() == null || i.getSouth() == null || i.getNorth() == null) return 0;
            double lat0 = Math.toRadians((i.getSouth() + i.getNorth()) / 2);
            double w = (i.getEast() - i.getWest()) * 111.32 * Math.cos(lat0);
            double h = (i.getNorth() - i.getSouth()) * 110.54;
            return Math.abs(w * h) * 100.0; // km² → ha
        }).sum();
        long supervised = records.stream().filter(e -> "SUPERVISED".equals(e.getMethod())).count();
        long fusion = records.stream().filter(e -> "FUSION".equals(e.getMethod())).count();
        String latestDate = records.stream()
                .map(Extraction::getAcquisitionDate).filter(java.util.Objects::nonNull)
                .max(Comparator.naturalOrder()).map(String::valueOf).orElse("-");

        Map<String, Object> kpi = new LinkedHashMap<>();
        kpi.put("imageryCount", imgs.size());
        kpi.put("imageryAreaHa", round2(imageryHa));
        kpi.put("extractionCount", records.size());
        kpi.put("extractionAreaHa", round2(extractHa));
        kpi.put("supervisedCount", supervised);
        kpi.put("fusionCount", fusion);
        kpi.put("boundaryCount", boundaryRepo.count());
        kpi.put("latestDate", latestDate);

        // ---- 地物构成（按类累计 + 最新一期）----
        Map<String, double[]> byClass = new TreeMap<>();
        Map<String, String> lastDateOfClass = new TreeMap<>();
        for (Extraction e : records) {
            String cls = e.getClassType() == null ? "UNKNOWN" : e.getClassType();
            double[] acc = byClass.computeIfAbsent(cls, k -> new double[2]);
            acc[0] += e.getExtractAreaHa() == null ? 0 : e.getExtractAreaHa();
            acc[1] += 1;
            String d = e.getAcquisitionDate() == null ? "" : e.getAcquisitionDate().toString();
            if (d.compareTo(lastDateOfClass.getOrDefault(cls, "")) >= 0) {
                lastDateOfClass.put(cls, d);
                acc[1] = acc[1]; // 记录数已在上面累加
            }
        }
        List<Map<String, Object>> classes = new ArrayList<>();
        byClass.entrySet().stream()
                .sorted((a, b) -> Double.compare(b.getValue()[0], a.getValue()[0]))
                .forEach(en -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("classType", en.getKey());
                    m.put("totalHa", round2(en.getValue()[0]));
                    m.put("recordCount", (int) en.getValue()[1]);
                    classes.add(m);
                });

        // ---- 按期时序（按拍摄日期聚合成堆叠柱）----
        Map<String, Map<String, Double>> byDate = new TreeMap<>();
        for (Extraction e : records) {
            String d = e.getAcquisitionDate() == null ? "-" : e.getAcquisitionDate().toString();
            String cls = e.getClassType() == null ? "UNKNOWN" : e.getClassType();
            byDate.computeIfAbsent(d, k -> new LinkedHashMap<>())
                    .merge(cls, e.getExtractAreaHa() == null ? 0 : e.getExtractAreaHa(), Double::sum);
        }
        // 注意：lambda 里只能捕获 effectively-final 变量，所以先放 seriesAll，再裁剪给 series
        final List<Map<String, Object>> seriesAll = new ArrayList<>();
        byDate.forEach((date, m) -> {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("date", date);
            double total = m.values().stream().mapToDouble(Double::doubleValue).sum();
            row.put("totalHa", round2(total));
            Map<String, Double> clean = new LinkedHashMap<>();
            m.forEach((k, v) -> clean.put(k, round2(v)));
            row.put("byClass", clean);
            seriesAll.add(row);
        });
        // 大屏只展示最近 10 期，避免柱子挤成一片
        List<Map<String, Object>> series = seriesAll.size() > 10
                ? new ArrayList<>(seriesAll.subList(seriesAll.size() - 10, seriesAll.size()))
                : seriesAll;

        // ---- 最近解译记录（按日期倒序取 8 条）----
        List<Extraction> sorted = new ArrayList<>(records);
        sorted.sort(Comparator
                .comparing((Extraction e) -> e.getAcquisitionDate() == null ? "" : e.getAcquisitionDate().toString())
                .thenComparing(Extraction::getId).reversed());
        List<Map<String, Object>> recent = new ArrayList<>();
        for (Extraction e : sorted.subList(0, Math.min(8, sorted.size()))) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", e.getId());
            m.put("name", e.getName());
            m.put("classType", e.getClassType());
            m.put("method", e.getMethod() == null ? "INDEX" : e.getMethod());
            m.put("date", e.getAcquisitionDate() == null ? "-" : e.getAcquisitionDate().toString());
            m.put("areaHa", e.getExtractAreaHa() == null ? 0 : round2(e.getExtractAreaHa()));
            m.put("coveragePct", e.getCoveragePct() == null ? 0 : e.getCoveragePct());
            recent.add(m);
        }

        // ---- 最近一次监督分类精度（有就显示，没有就不显示，不编数）----
        Map<String, Object> accuracy = null;
        for (Extraction e : sorted) {
            if (!"SUPERVISED".equals(e.getMethod())) continue;
            String raw = e.getAccuracyJson();
            if (raw == null || raw.isBlank()) continue;
            try {
                var node = mapper.readTree(raw);
                accuracy = new LinkedHashMap<>();
                accuracy.put("oa", node.path("overallAccuracy").asDouble(0));
                accuracy.put("kappa", node.path("kappa").asDouble(0));
                accuracy.put("split", node.path("split").asText("-"));
                accuracy.put("classType", e.getClassType());
                accuracy.put("date", e.getAcquisitionDate() == null ? "-" : e.getAcquisitionDate().toString());
                break;
            } catch (Exception ignored) {
                // 解析失败就跳过，不阻断大屏
            }
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("kpi", kpi);
        out.put("classes", classes);
        out.put("series", series);
        out.put("recent", recent);
        out.put("accuracy", accuracy);
        return ApiResponse.ok(out);
    }

    private static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
