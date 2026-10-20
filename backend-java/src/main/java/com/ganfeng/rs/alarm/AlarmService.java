package com.ganfeng.rs.alarm;

import com.ganfeng.rs.common.BizException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 告警服务（MySQL 持久化）
 * 真实链路：IoT 阈值引擎命中规则 -> 写入告警 -> WebSocket 推送
 */
@Service
public class AlarmService {

    private final AlarmRepository repo;

    public AlarmService(AlarmRepository repo) {
        this.repo = repo;
    }

    public List<Alarm> list(Long projectId) {
        return projectId == null ? repo.findAll() : repo.findByProjectIdOrderByCreatedAtDesc(projectId);
    }

    /** 确认告警：只有未确认状态可以确认 */
    @Transactional
    public Alarm ack(long id) {
        Alarm a = repo.findById(id).orElseThrow(() -> BizException.notFound("告警不存在: " + id));
        if (!"UNACK".equals(a.getStatus())) {
            throw BizException.badRequest("该告警已处理，无需重复确认");
        }
        a.setStatus("ACKED");
        return repo.save(a);
    }

    /**
     * 闭环处理：认领 → 处理 → 关闭（UNACK/ACKED → RESOLVED）。
     * 记录处理人、处理意见、处理时间，实现「产生→认领→处理→关闭」全流程闭环。
     */
    @Transactional
    public Alarm resolve(long id, String handledBy, String handleComment) {
        Alarm a = repo.findById(id).orElseThrow(() -> BizException.notFound("告警不存在: " + id));
        if ("RESOLVED".equals(a.getStatus())) {
            throw BizException.badRequest("该告警已关闭");
        }
        a.setStatus("RESOLVED");
        a.setHandledBy(handledBy);
        a.setHandleComment(handleComment);
        a.setHandleTime(java.time.LocalDateTime.now());
        return repo.save(a);
    }

    /**
     * 写入一条遥感变化趋势告警（变化检测自动预警）。
     * 供 AnalysisController 检测到面积环比超阈值时调用，alarmType=RS_TREND。
     */
    @Transactional
    public Alarm createTrendAlarm(Long projectId, String classType, String indicator,
                                  Double changePct, Double threshold) {
        Alarm a = new Alarm(projectId, "RS-TREND", classType, "ORANGE", indicator,
                changePct, threshold, "%", "UNACK", java.time.LocalDateTime.now());
        a.setAlarmType("RS_TREND");
        return repo.save(a);
    }
}
