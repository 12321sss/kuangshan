/**
 * 面积单位换算工具
 *
 * 全平台面积**底层统一存公顷(ha)**（数据库字段、Java 实体、inference 回调协议都基于 ha，
 * 改字段名会引发连锁改动），仅在**展示层**换算成用户友好的单位。
 *
 * 换算关系：1 km² = 100 ha；1 ha = 10000 m²
 */

/** 公顷 → 平方千米（保留 2 位小数），返回字符串，如 "12.34" */
export function haToKm2(ha: number | null | undefined): string {
  if (ha === null || ha === undefined || isNaN(ha)) return '-'
  return (ha / 100).toFixed(2)
}

/** 公顷 → 平方千米（数字，保留 2 位），用于图表/计算 */
export function haToKm2Num(ha: number | null | undefined): number {
  if (ha === null || ha === undefined || isNaN(ha)) return 0
  return Math.round(ha / 100 * 100) / 100
}

/** 带单位的面积展示：自动选择合适单位（≥1km² 用 km²，否则用 m²） */
export function formatArea(ha: number | null | undefined): string {
  if (ha === null || ha === undefined || isNaN(ha)) return '-'
  const km2 = ha / 100
  if (km2 >= 1) {
    return `${km2.toFixed(2)} km²`
  }
  const m2 = ha * 10000
  if (m2 >= 1) {
    return `${Math.round(m2)} m²`
  }
  return `${ha.toFixed(2)} ha`
}
