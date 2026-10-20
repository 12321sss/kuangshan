package com.ganfeng.rs.sensor;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface SensorRepository extends JpaRepository<Sensor, String> {

    List<Sensor> findByProjectId(Long projectId);
}
