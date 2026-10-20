package com.ganfeng.rs.station;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface StationRepository extends JpaRepository<Station, String> {

    List<Station> findByProjectIdOrderByIdAsc(Long projectId);
}
