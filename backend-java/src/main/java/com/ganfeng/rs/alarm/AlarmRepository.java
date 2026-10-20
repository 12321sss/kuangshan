package com.ganfeng.rs.alarm;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface AlarmRepository extends JpaRepository<Alarm, Long> {

    List<Alarm> findByProjectIdOrderByCreatedAtDesc(Long projectId);
}
