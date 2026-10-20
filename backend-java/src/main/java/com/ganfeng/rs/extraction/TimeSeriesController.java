package com.ganfeng.rs.extraction;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.PermissionGuard;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 时序接口：同一 AOI 的多期提取结果按时间组织，供前端时间轴播放
 *
 * 背景：客户演示最关心「这一片区域这些年怎么变的」。单期提取结果说明不了问题，
 * 必须把同一区域的多个时点串起来看——这就是时序播放的价值。
 *
 * 分组依据：aoi_signature（AOI 归一化指纹）。前端先按 signature 分组，
 * 选中一组后调本接口取该组的时序序列。
 */
@RestController
@RequestMapping("/api/timeseries")
public class TimeSeriesController {

    private final ExtractionService service;
    private final PermissionGuard guard;

    public TimeSeriesController(ExtractionService service, PermissionGuard guard) {
        this.service = service;
        this.guard = guard;
    }

    /**
     * 按 AOI 指纹分组返回所有时序组，前端可切换查看不同区域的变化过程。
     * 返回每组的：签名、AOI、类别、期数、时间范围、总面积变化。
     */
    @GetMapping("/groups")
    public ApiResponse<List<Map<String, Object>>> groups(@RequestParam(required = false) Long projectId,
                                                        Authentication auth) {
        List<Extraction> all = service.list(projectId, auth.getName(),
                guard.roleCodesOf(auth).contains("ADMIN"));

        // 按 signature 聚合（无 signature 的旧数据跳过）
        Map<String, List<Extraction>> grouped = new LinkedHashMap<>();
        for (Extraction e : all) {
            String sig = e.getAoiSignature();
            if (sig == null || sig.isBlank()) {
                continue;
            }
            grouped.computeIfAbsent(sig, k -> new ArrayList<>()).add(e);
        }

        List<Map<String, Object>> out = new ArrayList<>();
        grouped.forEach((sig, items) -> {
            // 组内按拍摄日期升序（时序播放顺序）
            items.sort(Comparator.comparing(
                    (Extraction x) -> x.getAcquisitionDate() == null ? "" : x.getAcquisitionDate().toString())
                    .thenComparing(Extraction::getId));

            Extraction first = items.get(0);
            Extraction last = items.get(items.size() - 1);
            double areaChange = last.getExtractAreaHa() - first.getExtractAreaHa();

            Map<String, Object> g = new LinkedHashMap<>();
            g.put("signature", sig);
            g.put("aoiJson", first.getAoiJson());
            g.put("classType", first.getClassType());
            g.put("periodCount", items.size());
            g.put("startDate", first.getAcquisitionDate());
            g.put("endDate", last.getAcquisitionDate());
            g.put("startAreaHa", first.getExtractAreaHa());
            g.put("endAreaHa", last.getExtractAreaHa());
            g.put("areaChangeHa", Math.round(areaChange * 100.0) / 100.0);
            g.put("changePct", first.getExtractAreaHa() > 0
                    ? Math.round(areaChange / first.getExtractAreaHa() * 1000.0) / 10.0 : 0.0);
            // 展示名：用 AOI 面积（km²）+ 地物类型，便于用户辨认区域
            double aoiHa = first.getAoiAreaHa() != null ? first.getAoiAreaHa() : 0;
            g.put("label", Math.round(aoiHa / 100.0 * 100.0) / 100.0
                    + " km² · " + (first.getClassType()));
            out.add(g);
        });

        // 期数多的排前面（同 AOI 多期最值得看）
        out.sort(Comparator.comparingInt((Map<String, Object> m) ->
                (Integer) m.get("periodCount")).reversed());
        return ApiResponse.ok(out);
    }

    /**
     * 取某个 AOI 组的完整时序序列（按日期升序），含每期的多边形几何。
     * 前端用它驱动时间轴播放。
     */
    @GetMapping("/{signature}")
    public ApiResponse<List<Map<String, Object>>> sequence(@PathVariable String signature,
                                                          Authentication auth) {
        List<Extraction> all = service.list(null, auth.getName(),
                guard.roleCodesOf(auth).contains("ADMIN"));
        List<Extraction> items = new ArrayList<>();
        for (Extraction e : all) {
            if (signature.equals(e.getAoiSignature())) {
                items.add(e);
            }
        }
        items.sort(Comparator.comparing(
                (Extraction x) -> x.getAcquisitionDate() == null ? "" : x.getAcquisitionDate().toString())
                .thenComparing(Extraction::getId));

        List<Map<String, Object>> out = new ArrayList<>();
        for (Extraction e : items) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", e.getId());
            m.put("date", e.getAcquisitionDate());
            m.put("name", e.getName());
            m.put("imageryId", e.getImageryId());
            m.put("satellite", e.getSatellite());
            m.put("classType", e.getClassType());
            m.put("featuresJson", e.getFeaturesJson());
            m.put("extractAreaHa", e.getExtractAreaHa());
            m.put("coveragePct", e.getCoveragePct());
            m.put("aoiAreaHa", e.getAoiAreaHa());
            out.add(m);
        }
        return ApiResponse.ok(out);
    }
}