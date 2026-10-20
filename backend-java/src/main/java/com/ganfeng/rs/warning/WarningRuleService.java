package com.ganfeng.rs.warning;

import com.ganfeng.rs.common.BizException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 预警规则服务（MySQL 持久化）
 */
@Service
public class WarningRuleService {

    private final WarningRuleRepository repo;

    public WarningRuleService(WarningRuleRepository repo) {
        this.repo = repo;
    }

    public List<WarningRule> list() {
        return repo.findAll();
    }

    /** 更新阈值：三级阈值必须满足 黄 <= 橙 <= 红，否则拒绝 */
    @Transactional
    public WarningRule update(long id, WarningRule req) {
        WarningRule existing = repo.findById(id)
                .orElseThrow(() -> BizException.notFound("预警规则不存在: " + id));
        if (!(req.getYellowThreshold() <= req.getOrangeThreshold()
                && req.getOrangeThreshold() <= req.getRedThreshold())) {
            throw BizException.badRequest("阈值必须满足：黄色 <= 橙色 <= 红色");
        }
        existing.setIndicator(req.getIndicator());
        existing.setUnit(req.getUnit());
        existing.setYellowThreshold(req.getYellowThreshold());
        existing.setOrangeThreshold(req.getOrangeThreshold());
        existing.setRedThreshold(req.getRedThreshold());
        existing.setEnabled(req.getEnabled());
        return repo.save(existing);
    }
}
