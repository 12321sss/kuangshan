package com.ganfeng.rs.sensor;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.LocalDateTime;

/**
 * 传感器设备（sensors 表）
 * type: DISP 位移 / RAIN 雨量 / SOIL 土壤含水率 / WATER 水位
 * status: ONLINE / OFFLINE / ALARM
 * 经纬度为演示便利暂存本表；接入空间库后迁移到 rs_geo.sensor_locations
 */
@Entity
@Table(name = "sensors")
public class Sensor {

    @Id
    @Column(length = 32)
    private String id;

    @Column(nullable = false)
    private Long projectId;

    @Column(nullable = false, length = 64)
    private String name;

    @Column(nullable = false, length = 16)
    private String type;

    @Column(nullable = false)
    private Double lng;

    @Column(nullable = false)
    private Double lat;

    @Column(nullable = false, length = 16)
    private String status = "ONLINE";

    @Column(nullable = false)
    private Double latestValue = 0.0;

    @Column(length = 16)
    private String unit;

    @Column(nullable = false)
    private LocalDateTime updatedAt = LocalDateTime.now();

    protected Sensor() {}

    public Sensor(String id, Long projectId, String name, String type, double lng, double lat,
                  String status, double latestValue, String unit) {
        this.id = id;
        this.projectId = projectId;
        this.name = name;
        this.type = type;
        this.lng = lng;
        this.lat = lat;
        this.status = status;
        this.latestValue = latestValue;
        this.unit = unit;
    }

    public String getId() { return id; }
    public Long getProjectId() { return projectId; }
    public String getName() { return name; }
    public String getType() { return type; }
    public Double getLng() { return lng; }
    public Double getLat() { return lat; }
    public String getStatus() { return status; }
    public Double getLatestValue() { return latestValue; }
    public String getUnit() { return unit; }
    public LocalDateTime getUpdatedAt() { return updatedAt; }

    public void setProjectId(Long projectId) { this.projectId = projectId; }
    public void setName(String name) { this.name = name; }
    public void setType(String type) { this.type = type; }
    public void setLng(Double lng) { this.lng = lng; }
    public void setLat(Double lat) { this.lat = lat; }
    public void setStatus(String status) { this.status = status; }
    public void setLatestValue(Double latestValue) { this.latestValue = latestValue; }
    public void setUnit(String unit) { this.unit = unit; }
    public void setUpdatedAt(LocalDateTime updatedAt) { this.updatedAt = updatedAt; }
}
