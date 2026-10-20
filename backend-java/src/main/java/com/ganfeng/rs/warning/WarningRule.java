package com.ganfeng.rs.warning;

import jakarta.persistence.*;

/**
 * 预警规则（warning_rules 表）：按传感器类型配置三级阈值（黄/橙/红）
 * enabled=false 时该类型不参与告警判断
 */
@Entity
@Table(name = "warning_rules")
public class WarningRule {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** DISP / RAIN / SOIL / WATER */
    @Column(nullable = false, unique = true, length = 16)
    private String sensorType;

    @Column(nullable = false, length = 32)
    private String sensorTypeName;

    /** 监测指标名，如 "合位移" */
    @Column(length = 32)
    private String indicator;

    @Column(length = 16)
    private String unit;

    @Column(nullable = false)
    private Double yellowThreshold;

    @Column(nullable = false)
    private Double orangeThreshold;

    @Column(nullable = false)
    private Double redThreshold;

    @Column(nullable = false)
    private Boolean enabled = true;

    protected WarningRule() {}

    public WarningRule(String sensorType, String sensorTypeName, String indicator, String unit,
                       Double yellowThreshold, Double orangeThreshold, Double redThreshold, Boolean enabled) {
        this.sensorType = sensorType;
        this.sensorTypeName = sensorTypeName;
        this.indicator = indicator;
        this.unit = unit;
        this.yellowThreshold = yellowThreshold;
        this.orangeThreshold = orangeThreshold;
        this.redThreshold = redThreshold;
        this.enabled = enabled;
    }

    public Long getId() { return id; }
    public String getSensorType() { return sensorType; }
    public String getSensorTypeName() { return sensorTypeName; }
    public String getIndicator() { return indicator; }
    public String getUnit() { return unit; }
    public Double getYellowThreshold() { return yellowThreshold; }
    public Double getOrangeThreshold() { return orangeThreshold; }
    public Double getRedThreshold() { return redThreshold; }
    public Boolean getEnabled() { return enabled; }

    public void setIndicator(String indicator) { this.indicator = indicator; }
    public void setUnit(String unit) { this.unit = unit; }
    public void setYellowThreshold(Double v) { this.yellowThreshold = v; }
    public void setOrangeThreshold(Double v) { this.orangeThreshold = v; }
    public void setRedThreshold(Double v) { this.redThreshold = v; }
    public void setEnabled(Boolean enabled) { this.enabled = enabled; }
}
