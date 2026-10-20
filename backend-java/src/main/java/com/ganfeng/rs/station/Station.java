package com.ganfeng.rs.station;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * 监测站点档案（stations 表）：站点是设备管理单元，sensorId 关联传感器数据源
 */
@Entity
@Table(name = "stations")
public class Station {

    @Id
    @Column(length = 32)
    private String id;

    @Column(nullable = false)
    private Long projectId;

    @Column(length = 32)
    private String projectNo;

    @Column(length = 128)
    private String region;

    @Column(nullable = false, length = 64)
    private String stationName;

    @Column(length = 64)
    private String stationType;

    /** NORMAL 正常 / ABNORMAL 异常 / MAINTAIN 维护 */
    @Column(nullable = false, length = 16)
    private String workStatus = "NORMAL";

    @Column(length = 32)
    private String firstMonitorAt;

    @Column(length = 32)
    private String lastMonitorAt;

    @Column(length = 32)
    private String deviceSn;

    @Column(length = 16)
    private String deviceWorkStatus = "正常";

    @Column(length = 32)
    private String deviceModel;

    @Column(length = 32)
    private String firmware;

    /** 关联的传感器数据源 id（可为空） */
    @Column(length = 32)
    private String sensorId;

    public Station() {}

    public String getId() { return id; }
    public Long getProjectId() { return projectId; }
    public String getProjectNo() { return projectNo; }
    public String getRegion() { return region; }
    public String getStationName() { return stationName; }
    public String getStationType() { return stationType; }
    public String getWorkStatus() { return workStatus; }
    public String getFirstMonitorAt() { return firstMonitorAt; }
    public String getLastMonitorAt() { return lastMonitorAt; }
    public String getDeviceSn() { return deviceSn; }
    public String getDeviceWorkStatus() { return deviceWorkStatus; }
    public String getDeviceModel() { return deviceModel; }
    public String getFirmware() { return firmware; }
    public String getSensorId() { return sensorId; }

    public void setId(String id) { this.id = id; }
    public void setProjectId(Long projectId) { this.projectId = projectId; }
    public void setProjectNo(String projectNo) { this.projectNo = projectNo; }
    public void setRegion(String region) { this.region = region; }
    public void setStationName(String stationName) { this.stationName = stationName; }
    public void setStationType(String stationType) { this.stationType = stationType; }
    public void setWorkStatus(String workStatus) { this.workStatus = workStatus; }
    public void setFirstMonitorAt(String firstMonitorAt) { this.firstMonitorAt = firstMonitorAt; }
    public void setLastMonitorAt(String lastMonitorAt) { this.lastMonitorAt = lastMonitorAt; }
    public void setDeviceSn(String deviceSn) { this.deviceSn = deviceSn; }
    public void setDeviceWorkStatus(String deviceWorkStatus) { this.deviceWorkStatus = deviceWorkStatus; }
    public void setDeviceModel(String deviceModel) { this.deviceModel = deviceModel; }
    public void setFirmware(String firmware) { this.firmware = firmware; }
    public void setSensorId(String sensorId) { this.sensorId = sensorId; }
}
