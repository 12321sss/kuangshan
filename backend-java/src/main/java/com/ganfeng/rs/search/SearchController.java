package com.ganfeng.rs.search;

import com.ganfeng.rs.alarm.AlarmRepository;
import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.extraction.ExtractionRepository;
import com.ganfeng.rs.imagery.ImageryRepository;
import com.ganfeng.rs.project.ProjectRepository;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 全局搜索：聚合工程 / 影像 / 解译记录 / 告警四类实体的名称字段。
 *
 * demo 数据量小（百级），直接在内存做包含匹配即可；
 * 生产期应改为各表加全文索引或接 ES。
 */
@RestController
@RequestMapping("/api/search")
public class SearchController {

    private final ProjectRepository projectRepo;
    private final ImageryRepository imageryRepo;
    private final ExtractionRepository extractionRepo;
    private final AlarmRepository alarmRepo;

    private final com.ganfeng.rs.project.ProjectService projectService;

    public SearchController(ProjectRepository projectRepo, ImageryRepository imageryRepo,
                            ExtractionRepository extractionRepo, AlarmRepository alarmRepo,
                            com.ganfeng.rs.project.ProjectService projectService) {
        this.projectRepo = projectRepo;
        this.imageryRepo = imageryRepo;
        this.extractionRepo = extractionRepo;
        this.alarmRepo = alarmRepo;
        this.projectService = projectService;
    }

    @GetMapping
    public ApiResponse<List<Map<String, Object>>> search(@RequestParam String keyword,
                                                         org.springframework.security.core.Authentication auth) {
        String kw = keyword == null ? "" : keyword.trim().toLowerCase();
        List<Map<String, Object>> hits = new ArrayList<>();
        if (kw.isEmpty()) {
            return ApiResponse.ok(hits);
        }

        // 项目隔离：只搜当前用户可见的项目及其下数据。
        // 修复前这里直接 findAll() 全表扫描，任何登录用户都能搜出别人项目的影像/解译/告警名称。
        boolean isAdmin = auth != null && auth.getAuthorities().stream()
                .anyMatch(a -> "ROLE_ADMIN".equals(a.getAuthority()));
        java.util.Set<Long> visible = projectService.listForUser(
                        auth == null ? "" : auth.getName(), isAdmin)
                .stream().map(com.ganfeng.rs.project.Project::getId)
                .collect(java.util.stream.Collectors.toSet());
        if (visible.isEmpty()) {
            return ApiResponse.ok(hits);
        }

        projectRepo.findAll().stream()
                .filter(p -> visible.contains(p.getId()))
                .forEach(p -> {
                    if (contains(p.getName(), kw) || contains(p.getRegion(), kw)) {
                        hits.add(hit("PROJECT", "工程", p.getName(), "/platform/projects"));
                    }
                });

        imageryRepo.findAll().stream()
                .filter(i -> i.getProjectId() != null && visible.contains(i.getProjectId()))
                .forEach(i -> {
                    String name = safeName(i);
                    if (contains(name, kw)) {
                        hits.add(hit("IMAGERY", "影像", name, "/imagery"));
                    }
                });

        extractionRepo.findAll().stream()
                .filter(e -> e.getProjectId() != null && visible.contains(e.getProjectId()))
                .forEach(e -> {
                    if (contains(e.getName(), kw) || contains(e.getClassType(), kw)) {
                        hits.add(hit("EXTRACTION", "解译", e.getName(), "/remote-extract"));
                    }
                });

        alarmRepo.findAll().stream()
                .filter(a -> a.getProjectId() != null && visible.contains(a.getProjectId()))
                .forEach(a -> {
                    if (contains(a.getSensorName(), kw) || contains(a.getIndicator(), kw)) {
                        hits.add(hit("ALARM", "告警", a.getSensorName() + " · " + a.getIndicator(), "/warning/alarms"));
                    }
                });

        // 最多返回 20 条，避免下拉过长
        return ApiResponse.ok(hits.size() > 20 ? hits.subList(0, 20) : hits);
    }

    private static Map<String, Object> hit(String type, String typeLabel, String name, String path) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("type", type);
        m.put("typeLabel", typeLabel);
        m.put("name", name == null ? "-" : name);
        m.put("path", path);
        return m;
    }

    private static boolean contains(String src, String kw) {
        return src != null && src.toLowerCase().contains(kw);
    }

    /** Imagery 实体字段名差异兜底：优先 name，其次 fileName */
    private static String safeName(Object imagery) {
        try {
            Object v = imagery.getClass().getMethod("getName").invoke(imagery);
            if (v != null) return v.toString();
        } catch (Exception ignored) { /* fall through */ }
        try {
            Object v = imagery.getClass().getMethod("getFileName").invoke(imagery);
            if (v != null) return v.toString();
        } catch (Exception ignored) { /* fall through */ }
        return "-";
    }
}
