package com.ganfeng.rs.sensor;

import java.time.LocalDateTime;

/**
 * 传感器时序数据点
 */
public record SensorDataPoint(LocalDateTime time, double value) {}
