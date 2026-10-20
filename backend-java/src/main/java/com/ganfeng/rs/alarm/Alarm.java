package com.ganfeng.rs.alarm;

import jakarta.persistence.*;

import java.time.LocalDateTime;

/**
 * 告警记录（alarms 表，追加型：只允许状态流转，不提供物理删除）
 * level: RED 红色 / ORANGE 橙色 / YELLOW 黄色 / BLUE 蓝色
 * status: UNACK 未确认 / ACKED 已确认 / RESOLVED 已解除
 */
@Entity
@Table(name = "alarms")
public class Alarm {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long projectId;

    @Column(nullable = false, length = 32)
    private String sensorId;

    @Column(nullable = false, length = 64)
    private String sensorName;

    @Column(nullable = false, length = 16)
    private String level;

    @Column(length = 32)
    private String indicator;

    @Column(nullable = false)
    private Double value;

    @Column(nullable = false)
    private Double threshold;

    @Column(length = 16)
    private String unit;

    @Column(nullable = false, length = 16)
    private String status = "UNACK";

    /** 告警来源类型：SENSOR 传感器阈值 / RS_TREND 遥感变化趋势 */
    @Column(nullable = false, length = 16)
    private String alarmType = "SENSOR";

    @Column(nullable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    /** 闭环字段：处理人、处理意见、处理时间（RESOLVED 时必填） */
    @Column(length = 64)
    private String handledBy;

    @Column(length = 512)
    private String handleComment;

    @Column
    private LocalDateTime handleTime;

    protected Alarm() {}

    public Alarm(Long projectId, String sensorId, String sensorName, String level, String indicator,
                 Double value, Double threshold, String unit, String status, LocalDateTime createdAt) {
        this.projectId = projectId;
        this.sensorId = sensorId;
        this.sensorName = sensorName;
        this.level = level;
        this.indicator = indicator;
        this.value = value;
        this.threshold = threshold;
        this.unit = unit;
        this.status = status;
        this.createdAt = createdAt;
    }

    public Long getId() { return id; }
    public Long getProjectId() { return projectId; }
    public String getSensorId() { return sensorId; }
    public String getSensorName() { return sensorName; }
    public String getLevel() { return level; }
    public String getIndicator() { return indicator; }
    public Double getValue() { return value; }
    public Double getThreshold() { return threshold; }
    public String getUnit() { return unit; }
    public String getStatus() { return status; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public String getAlarmType() { return alarmType; }
    public String getHandledBy() { return handledBy; }
    public String getHandleComment() { return handleComment; }
    public LocalDateTime getHandleTime() { return handleTime; }

    public void setStatus(String status) { this.status = status; }
    public void setAlarmType(String alarmType) { this.alarmType = alarmType; }
    public void setHandledBy(String handledBy) { this.handledBy = handledBy; }
    public void setHandleComment(String handleComment) { this.handleComment = handleComment; }
    public void setHandleTime(LocalDateTime handleTime) { this.handleTime = handleTime; }
}
