package com.ganfeng.rs.analysis;

import com.ganfeng.rs.common.ApiResponse;
import com.ganfeng.rs.common.PermissionGuard;
import com.ganfeng.rs.extraction.Extraction;
import com.ganfeng.rs.extraction.ExtractionService;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * 遥感监测分析（**基于真实解译结果聚合**，不再硬编码）
 *
 * 变更说明：原实现用写死的数组出图（采坑面积 {12.4, 15.8, 21.6...}）——
 * 那是演示数据不是分析结果。现在改为从 extractions 表按影像拍摄日期聚合，
 * 数据可追溯到每一次真实解译，报告里的数字才有依据。
 *
 * 口径红线：采坑面积 = 该时期所有 PIT 类提取面积之和；
 * 「预测」是趋势外推**非实测**，接口响应里带method/disclaimer，前端与报告须原样展示。
 */
@RestController
@RequestMapping("/api/analysis")
public class AnalysisController {

    private final ExtractionService extractionService;
    private final PermissionGuard guard;
    private final com.ganfeng.rs.alarm.AlarmService alarmService;

    public AnalysisController(ExtractionService extractionService, PermissionGuard guard,
                              com.ganfeng.rs.alarm.AlarmService alarmService) {
        this.extractionService = extractionService;
        this.guard = guard;
        this.alarmService = alarmService;
    }

    /**
     * 变化检测自动预警（demo 手动触发版）：对时序数据做环比增幅检测，
     * 某类地物面积环比增长超过阈值时生成一条 RS_TREND 告警。
     * 生产期改为定时任务；demo 期手动触发更可控、更便于演示。
     */
    @PostMapping("/check-trends")
    public ApiResponse<Map<String, Object>> checkTrends(@RequestParam(required = false) Long projectId,
                                                        @RequestParam(defaultValue = "20") double thresholdPct,
                                                        Authentication auth) {
        guard.require(auth, "action:rule-edit");   // 预警配置权限
        List<Extraction> all = extractionService.list(projectId, auth.getName(),
                guard.roleCodesOf(auth).contains("ADMIN"));

        // 先去重：同一区域同一期重复提取只取最新一次，否则会算出接近 0 的虚假环比
        Map<String, Extraction> dedup = new LinkedHashMap<>();
        for (Extraction e : all) {
            String period = periodOf(e, false);
            String aoiSig = (e.getAoiSignature() == null || e.getAoiSignature().isBlank())
                    ? "single-" + e.getId()
                    : e.getAoiSignature();
            String key = period + "|" + e.getClassType() + "|" + aoiSig;
            Extraction exist = dedup.get(key);
            if (exist == null || newerObservation(e, exist)) {
                dedup.put(key, e);
            }
        }

        // 按 classType + AOI 签名分组，组内按日期排序算环比
        Map<String, List<Extraction>> groups = new LinkedHashMap<>();
        for (Extraction e : dedup.values()) {
            String aoiSig = (e.getAoiSignature() == null || e.getAoiSignature().isBlank())
                    ? "single-" + e.getId()
                    : e.getAoiSignature();
            String key = e.getClassType() + "@" + aoiSig;
            groups.computeIfAbsent(key, k -> new ArrayList<>()).add(e);
        }

        List<Map<String, Object>> triggered = new ArrayList<>();
        int comparableGroups = 0;   // 有 2 期以上、可做环比的分组数
        for (Map.Entry<String, List<Extraction>> en : groups.entrySet()) {
            List<Extraction> items = en.getValue();
            items.sort(java.util.Comparator.comparing(
                    (Extraction x) -> x.getAcquisitionDate() == null ? "" : x.getAcquisitionDate().toString()));
            if (items.size() < 2) continue;
            comparableGroups++;
            Extraction prev = items.get(items.size() - 2);
            Extraction last = items.get(items.size() - 1);
            double prevArea = nz(prev.getExtractAreaHa());
            double lastArea = nz(last.getExtractAreaHa());
            if (prevArea <= 0) continue;
            double changePct = (lastArea - prevArea) / prevArea * 100;
            if (changePct >= thresholdPct) {
                String classType = en.getKey().split("@")[0];
                // 落库一条趋势告警（复用告警闭环体系）
                alarmService.createTrendAlarm(
                        projectId, classType,
                        classType + "面积环比增长", round2(changePct), thresholdPct);
                triggered.add(Map.of("classType", classType, "changePct", round2(changePct)));
            }
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("triggered", triggered);
        out.put("thresholdPct", thresholdPct);
        out.put("comparableGroups", comparableGroups);
        if (comparableGroups == 0) {
            out.put("message", "暂无可比数据：需要同一 AOI 至少 2 期解译记录才能检测面积变化");
        } else if (triggered.isEmpty()) {
            out.put("message", String.format("已检测 %d 组时序，未发现环比增幅超过 %.0f%% 的变化",
                    comparableGroups, thresholdPct));
        } else {
            out.put("message", String.format("检测到 %d 处超阈值变化，已生成趋势告警（见告警日志）",
                    triggered.size()));
        }
        return ApiResponse.ok(out);
    }

    /**
     * 地物面积时序（按年/月聚合，**存量口径**）
     *
     * 关键设计（避免"多次提取导致面积翻倍"）：
     * 地物面积是存量指标 —— 同一 AOI、同一地物类型、同一期（年月）内多次提取，
     * 代表的是同一块地的重复测量，**只能取最新一次**，绝不能相加。
     * 只有空间上不同的 AOI 之间才允许求和（地块不重叠）。
     *
     * @param classType   可选：只统计某一类
     * @param granularity month（默认）/ year
     */
    @GetMapping("/area-timeseries")
    public ApiResponse<Map<String, Object>> areaTimeseries(
            @RequestParam(required = false) Long projectId,
            @RequestParam(required = false) String classType,
            @RequestParam(defaultValue = "month") String granularity,
            Authentication auth) {
        List<Extraction> all = extractionService.list(projectId, auth.getName(),
                guard.roleCodesOf(auth).contains("ADMIN"));

        boolean byYear = "year".equalsIgnoreCase(granularity);

        // 第一步：按 (期 | 地物类型 | AOI 指纹) 去重，保留 id 最大（即最新一次提取）
        // aoiSignature 缺失的旧数据用 id 兜底，保证不会被误合并
        Map<String, Extraction> dedup = new LinkedHashMap<>();
        for (Extraction e : all) {
            if (classType != null && !classType.isBlank()
                    && !classType.equalsIgnoreCase(e.getClassType())) {
                continue;
            }
            String period = periodOf(e, byYear);
            String aoiSig = (e.getAoiSignature() == null || e.getAoiSignature().isBlank())
                    ? "single-" + e.getId()
                    : e.getAoiSignature();
            String key = period + "|" + e.getClassType() + "|" + aoiSig;
            Extraction exist = dedup.get(key);
            if (exist == null || newerObservation(e, exist)) {
                dedup.put(key, e);
            }
        }

        // 第二步：按 期 + 类型 求和（此时同一期内同一 AOI 已只保留一条）
        Map<String, Map<String, Double>> byPeriod = new TreeMap<>();
        int[] periodRecordCount = new int[1];
        Map<String, Integer> countsByPeriod = new LinkedHashMap<>();
        for (Extraction e : dedup.values()) {
            String period = periodOf(e, byYear);
            byPeriod.computeIfAbsent(period, k -> new LinkedHashMap<>())
                    .merge(e.getClassType(), nz(e.getExtractAreaHa()), Double::sum);
            countsByPeriod.merge(period, 1, Integer::sum);
        }

        List<Map<String, Object>> rows = new ArrayList<>();
        double prevTotal = 0;
        boolean first = true;
        for (Map.Entry<String, Map<String, Double>> en : byPeriod.entrySet()) {
            double total = 0;
            for (double v : en.getValue().values()) {
                total += v;
            }
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("date", en.getKey());
            row.put("totalAreaHa", round2(total));
            row.put("changeHa", first ? 0.0 : round2(total - prevTotal));
            row.put("byClass", en.getValue());
            row.put("recordCount", countsByPeriod.getOrDefault(en.getKey(), 0));
            rows.add(row);
            prevTotal = total;
            first = false;
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("granularity", byYear ? "year" : "month");
        out.put("rows", rows);
        // 说明口径，前端与报告原样展示，避免被理解成"累计"
        out.put("note", "同一区域同一期多次提取只取最新一次，不同区域面积相加；面积为存量指标，不可跨期累加。");
        return ApiResponse.ok(out);
    }

    /**
     * 单区域纵向体检：给定 AOI 指纹，汇总该区域内**所有地物类型**的历年变化。
     *
     * 与 area-timeseries 的区别：后者看的是"全项目某一类地物"，本接口看的是
     * "某一块地的全类型"，用来回答客户"这块地这些年到底怎么变的"。
     * 口径同样是存量：同区域同一期同一类型只取最新一次，不累加。
     */
    @GetMapping("/aoi-profile")
    public ApiResponse<Map<String, Object>> aoiProfile(
            @RequestParam(required = false) Long projectId,
            @RequestParam(required = false) String signature,
            Authentication auth) {
        List<Extraction> all = extractionService.list(projectId, auth.getName(),
                guard.roleCodesOf(auth).contains("ADMIN"));

        // 未指定签名时，自动选"记录最多"的区域（最有内容可看）
        if (signature == null || signature.isBlank()) {
            Map<String, Long> counts = new LinkedHashMap<>();
            for (Extraction e : all) {
                if (e.getAoiSignature() != null && !e.getAoiSignature().isBlank()) {
                    counts.merge(e.getAoiSignature(), 1L, Long::sum);
                }
            }
            signature = counts.entrySet().stream()
                    .max(Map.Entry.comparingByValue())
                    .map(Map.Entry::getKey)
                    .orElse(null);
        }
        if (signature == null) {
            Map<String, Object> empty = new LinkedHashMap<>();
            empty.put("signature", null);
            empty.put("message", "还没有可用于体检的区域数据");
            empty.put("classes", new ArrayList<>());
            empty.put("totalAreaHa", 0.0);
            return ApiResponse.ok(empty);
        }

        final String sig = signature;
        List<Extraction> areaRecords = all.stream()
                .filter(e -> sig.equals(e.getAoiSignature()))
                .toList();

        // 去重：期 | 类型 只保留日期最新
        Map<String, Extraction> dedup = new LinkedHashMap<>();
        for (Extraction e : areaRecords) {
            String key = periodOf(e, false) + "|" + e.getClassType();
            Extraction exist = dedup.get(key);
            if (exist == null || newerObservation(e, exist)) {
                dedup.put(key, e);
            }
        }

        // 按类型输出时序；按期间输出该期总覆盖
        Map<String, List<Map<String, Object>>> byClassSeries = new LinkedHashMap<>();
        Map<String, Double> periodTotal = new TreeMap<>();
        for (Extraction e : dedup.values()) {
            String period = periodOf(e, false);
            Map<String, Object> point = new LinkedHashMap<>();
            point.put("date", period);
            point.put("areaHa", round2(nz(e.getExtractAreaHa())));
            byClassSeries.computeIfAbsent(e.getClassType(), k -> new ArrayList<>()).add(point);
            periodTotal.merge(period, nz(e.getExtractAreaHa()), Double::sum);
        }
        byClassSeries.values().forEach(list -> list.sort(
                java.util.Comparator.comparing(m -> String.valueOf(m.get("date")))));

        // 当前构成：各类型最近一次提取
        Map<String, Extraction> latestPerClass = new LinkedHashMap<>();
        for (Extraction e : areaRecords) {
            Extraction exist = latestPerClass.get(e.getClassType());
            if (exist == null || newerObservation(e, exist)) {
                latestPerClass.put(e.getClassType(), e);
            }
        }
        List<Map<String, Object>> classes = new ArrayList<>();
        double totalNow = 0;
        for (Extraction e : latestPerClass.values()) {
            double ha = nz(e.getExtractAreaHa());
            totalNow += ha;
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("classType", e.getClassType());
            m.put("latestAreaHa", round2(ha));
            m.put("latestDate", e.getAcquisitionDate() == null ? null : e.getAcquisitionDate().toString());
            m.put("periodCount", byClassSeries.getOrDefault(e.getClassType(), List.of()).size());
            m.put("series", byClassSeries.getOrDefault(e.getClassType(), List.of()));
            classes.add(m);
        }
        classes.sort((a, b) -> Double.compare((Double) b.get("latestAreaHa"),
                (Double) a.get("latestAreaHa")));

        // 期间汇总（按时间升序，供折线图）
        List<Map<String, Object>> timeline = new ArrayList<>();
        double prev = 0;
        boolean first = true;
        for (Map.Entry<String, Double> en : periodTotal.entrySet()) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("date", en.getKey());
            row.put("totalAreaHa", round2(en.getValue()));
            row.put("changeHa", first ? 0.0 : round2(en.getValue() - prev));
            timeline.add(row);
            prev = en.getValue();
            first = false;
        }

        Extraction sample = areaRecords.isEmpty() ? null : areaRecords.get(0);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("signature", sig);
        out.put("classCount", classes.size());
        out.put("recordCount", areaRecords.size());
        out.put("totalAreaHa", round2(totalNow));
        out.put("classes", classes);
        out.put("timeline", timeline);
        out.put("note", "单区域体检：同一区域同一期同一类型只取最新一次提取，面积不累加。");
        return ApiResponse.ok(out);
    }

    /** 取某条记录所属的期：按月 YYYY-MM / 按年 YYYY */    private static String periodOf(Extraction e, boolean byYear) {
        if (e.getAcquisitionDate() != null) {
            String d = e.getAcquisitionDate().toString();
            return byYear ? d.substring(0, 4) : d.substring(0, 7);
        }
        if (e.getYear() != null) {
            return String.valueOf(e.getYear());
        }
        return byYear ? "未知年份" : "未知月份";
    }

    /**
     * 判断 candidate 是否比 current 更"新"：优先比拍摄日期，日期相同再比录入 id。
     *
     * 为什么不能只比 id：用户可能先提取 2024 年影像、再补录 2022 年影像，
     * 此时 id 大的反而是更早的影像，按 id 取会把真正的最近观测丢掉。
     */
    private static boolean newerObservation(Extraction candidate, Extraction current) {
        java.time.LocalDate dc = candidate.getAcquisitionDate();
        java.time.LocalDate dcur = current.getAcquisitionDate();
        if (dc != null && dcur != null && !dc.equals(dcur)) {
            return dc.isAfter(dcur);
        }
        if (dc != null && dcur == null) return true;
        if (dc == null && dcur != null) return false;
        return candidate.getId() > current.getId();
    }

    /** 同一 (类型|AOI) 去重，保留日期最新的一条 */
    private static Map<String, Extraction> dedupByAoi(List<Extraction> all, boolean filterPit,
                                                      Integer onlyYear) {
        Map<String, Extraction> latest = new LinkedHashMap<>();
        for (Extraction e : all) {
            if (filterPit && !"PIT".equalsIgnoreCase(e.getClassType())) continue;
            if (onlyYear != null && !onlyYear.equals(e.getYear())) continue;
            String aoiSig = (e.getAoiSignature() == null || e.getAoiSignature().isBlank())
                    ? "single-" + e.getId()
                    : e.getAoiSignature();
            String key = e.getClassType() + "|" + aoiSig;
            Extraction exist = latest.get(key);
            if (exist == null || newerObservation(e, exist)) {
                latest.put(key, e);
            }
        }
        return latest;
    }

    /**
     * 已废弃的旧实现（保留注释说明为何改）：
     * 原按 date 分组 + merge(sum) 会把同一区域重复提取的面积相加，
     * 用户提取两次即翻倍，导致数据失真。
     */
    @Deprecated
    private ApiResponse<List<Map<String, Object>>> areaTimeseriesLegacy(
            List<Extraction> all, String classType) {
        Map<String, Map<String, Double>> byDate = new TreeMap<>();
        for (Extraction e : all) {
            if (classType != null && !classType.isBlank()
                    && !classType.equalsIgnoreCase(e.getClassType())) {
                continue;
            }
            String date = e.getAcquisitionDate() != null
                    ? e.getAcquisitionDate().toString()
                    : (e.getYear() != null ? e.getYear() + "-01-01" : "未知日期");
            byDate.computeIfAbsent(date, k -> new LinkedHashMap<>())
                    .merge(e.getClassType(), nz(e.getExtractAreaHa()), Double::sum);
        }

        List<Map<String, Object>> out = new ArrayList<>();
        double prevTotal = 0;
        boolean first = true;
        for (Map.Entry<String, Map<String, Double>> en : byDate.entrySet()) {
            double total = 0;
            for (double v : en.getValue().values()) {
                total += v;
            }
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("date", en.getKey());
            row.put("totalAreaHa", round2(total));
            row.put("changeHa", first ? 0.0 : round2(total - prevTotal));
            row.put("byClass", en.getValue());
            out.add(row);
            prevTotal = total;
            first = false;
        }
        return ApiResponse.ok(out);
    }

    /**
     * 采坑扩张趋势预测：对真实序列做线性外推。
     *
     * 红线：趋势外推非实测。响应带 method/disclaimer/uncertainty，
     * 前端与报告必须原样展示，不能包装成「预测准确值」。
     * 期数不足 2 期时返回空数组 + insufficient 标记，**不编数**。
     */
    @GetMapping("/pit-forecast")
    public ApiResponse<Map<String, Object>> pitForecast(@RequestParam(required = false) Long projectId,
                                                        Authentication auth) {
        List<Extraction> all = extractionService.list(projectId, auth.getName(),
                guard.roleCodesOf(auth).contains("ADMIN"));

        // 去重：同一 AOI 同一月份（同一年月内重复提取）只保留最新一次，
        // 否则同月多提两次会被当成"两期"，外推斜率失真。
        Map<String, Extraction> pitByPeriodAoi = new LinkedHashMap<>();
        for (Extraction e : all) {
            if (!"PIT".equalsIgnoreCase(e.getClassType())) continue;
            String period = periodOf(e, false);  // 按月
            String aoiSig = (e.getAoiSignature() == null || e.getAoiSignature().isBlank())
                    ? "single-" + e.getId()
                    : e.getAoiSignature();
            String key = period + "|" + aoiSig;
            Extraction exist = pitByPeriodAoi.get(key);
            if (exist == null || newerObservation(e, exist)) {
                pitByPeriodAoi.put(key, e);
            }
        }
        List<Extraction> pits = pitByPeriodAoi.values().stream()
                .sorted(java.util.Comparator.comparing(
                        (Extraction x) -> x.getAcquisitionDate() == null
                                ? "" : x.getAcquisitionDate().toString()))
                .toList();

        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("method", "线性外推（末两期变化速率）");
        resp.put("disclaimer", "趋势外推，非实测结果；实际扩张速率受采矿计划、地形与政策等因素影响");

        if (pits.size() < 2) {
            resp.put("forecast", new ArrayList<>());
            resp.put("insufficient", true);
            resp.put("historyPeriods", pits.size());
            resp.put("message", "采坑类真实提取记录不足 2 期，无法做趋势外推");
            return ApiResponse.ok(resp);
        }

        Extraction last = pits.get(pits.size() - 1);
        Extraction prev = pits.get(pits.size() - 2);
        double lastArea = nz(last.getExtractAreaHa());
        double prevArea = nz(prev.getExtractAreaHa());
        double days = daysBetween(prev, last);
        double stepPerDay = (lastArea - prevArea) / days;

        // 不确定性带宽：历史各期变动量的标准差，随外推步长放大
        double[] deltas = new double[pits.size() - 1];
        for (int i = 1; i < pits.size(); i++) {
            deltas[i - 1] = nz(pits.get(i).getExtractAreaHa()) - nz(pits.get(i - 1).getExtractAreaHa());
        }
        double mean = 0;
        for (double d : deltas) {
            mean += d;
        }
        mean /= deltas.length;
        double var = 0;
        for (double d : deltas) {
            var += (d - mean) * (d - mean);
        }
        double sd = deltas.length > 1 ? Math.sqrt(var / (deltas.length - 1)) : Math.abs(mean);

        List<Map<String, Object>> forecast = new ArrayList<>();
        java.time.LocalDate baseDate = last.getAcquisitionDate();
        if (baseDate != null) {
            for (int i = 1; i <= 3; i++) {
                java.time.LocalDate d = baseDate.plusDays(Math.round(days * i));
                double mid = lastArea + stepPerDay * days * i;
                double band = sd * i * 1.5;      // 带宽随外推步长放大
                Map<String, Object> f = new LinkedHashMap<>();
                f.put("date", d.toString());
                f.put("areaHa", round2(Math.max(mid, 0)));
                f.put("lowerHa", round2(Math.max(mid - band, 0)));
                f.put("upperHa", round2(mid + band));
                f.put("uncertaintyHa", round2(band));
                forecast.add(f);
            }
        }

        resp.put("forecast", forecast);
        resp.put("insufficient", false);
        resp.put("historyPeriods", pits.size());
        resp.put("lastDate", baseDate == null ? null : baseDate.toString());
        resp.put("lastAreaHa", round2(lastArea));
        return ApiResponse.ok(resp);
    }

    /**
     * 地物构成概览（给大屏/报告用）
     *
     * 存量口径：每个地物类型取「该类型每个 AOI 的最近一次提取」，再按区域求和。
     * 不能把同一区域的历史多期面积累加（重复提取会翻倍）。
     * recordCount 是记录条数（计数可以累计，面积不行）。
     */
    @GetMapping("/change-summary")
    public ApiResponse<Map<String, Object>> changeSummary(@RequestParam(required = false) Long projectId,
                                                          Authentication auth) {
        List<Extraction> all = extractionService.list(projectId, auth.getName(),
                guard.roleCodesOf(auth).contains("ADMIN"));

        // 按 (类型 | AOI) 去重，保留**拍摄日期最新**的一条（不是 id 最新）
        Map<String, Integer> recordCountByClass = new LinkedHashMap<>();
        for (Extraction e : all) {
            recordCountByClass.merge(e.getClassType(), 1, Integer::sum);
        }
        Map<String, Extraction> latestPerAoi = dedupByAoi(all, false, null);

        Map<String, Double> areaByClass = new LinkedHashMap<>();
        for (Extraction e : latestPerAoi.values()) {
            areaByClass.merge(e.getClassType(), nz(e.getExtractAreaHa()), Double::sum);
        }

        List<Map<String, Object>> classes = new ArrayList<>();
        for (Map.Entry<String, Double> en : areaByClass.entrySet()) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("classType", en.getKey());
            m.put("totalAreaHa", round2(en.getValue()));
            m.put("recordCount", recordCountByClass.getOrDefault(en.getKey(), 0));
            classes.add(m);
        }
        classes.sort((a, b) -> Double.compare((Double) b.get("totalAreaHa"),
                (Double) a.get("totalAreaHa")));

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("totalRecords", all.size());
        out.put("classes", classes);
        out.put("note", "各类型取每个区域最近一次提取的面积（同一区域重复提取不累加）；recordCount 为历史记录条数。");
        return ApiResponse.ok(out);
    }

    private static double daysBetween(Extraction a, Extraction b) {
        if (a.getAcquisitionDate() == null || b.getAcquisitionDate() == null) {
            return 365;   // 缺日期时按年度步长近似
        }
        return Math.max(1, java.time.temporal.ChronoUnit.DAYS.between(
                a.getAcquisitionDate(), b.getAcquisitionDate()));
    }

    private static double nz(Double d) {
        return d == null ? 0.0 : d;
    }

    private static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}