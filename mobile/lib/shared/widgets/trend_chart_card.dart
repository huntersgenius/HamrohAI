import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../../core/l10n/app_localizations.dart';
import '../../core/theme/app_theme.dart';
import '../../data/models/models.dart';
import '../utils/formatters.dart';

/// One trend chart, rendered as a swipeable card (spec 4.2 tab 1, 5.2 tab 2).
///
/// The chart's job is to make "in range or not" legible at a glance, so the
/// target band is drawn behind the line and out-of-range points are marked in
/// the status colour rather than left to the reader to work out.
class TrendChartCard extends StatelessWidget {
  const TrendChartCard({
    super.key,
    required this.trend,
    this.onExport,
    this.onImport,
    this.onAddReading,
    this.isLoading = false,
  });

  final TrendData trend;
  final VoidCallback? onExport;

  /// Import is doctor-only (spec 5.2 tab 2).
  final VoidCallback? onImport;
  final VoidCallback? onAddReading;
  final bool isLoading;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final ThemeData theme = Theme.of(context);
    final MetricSeries series = trend.series;

    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: theme.cardTheme.color,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLg),
        border: Border.all(color: theme.dividerColor),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      l10n.fromMap(series.label, fallback: series.key),
                      style: theme.textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Text(
                      series.unit,
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.textTertiary,
                      ),
                    ),
                  ],
                ),
              ),
              if (trend.points.isNotEmpty) _LatestValue(trend: trend),
            ],
          ),
          const SizedBox(height: AppSpacing.lg),
          SizedBox(
            height: 170,
            child: isLoading
                ? const Center(child: CircularProgressIndicator(strokeWidth: 2))
                : trend.points.isEmpty
                    ? Center(
                        child: Text(
                          l10n.t('chart.no_data'),
                          style: const TextStyle(
                            color: AppColors.textTertiary,
                          ),
                        ),
                      )
                    : _Chart(trend: trend),
          ),
          if (trend.points.isNotEmpty) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            _Stats(trend: trend),
          ],
          const SizedBox(height: AppSpacing.md),
          const Divider(height: 1),
          const SizedBox(height: AppSpacing.sm),
          Row(
            children: <Widget>[
              if (onAddReading != null)
                TextButton.icon(
                  onPressed: onAddReading,
                  icon: const Icon(Icons.add_rounded, size: 18),
                  label: Text(l10n.t('chart.add_reading')),
                ),
              const Spacer(),
              if (onExport != null)
                IconButton(
                  onPressed: onExport,
                  tooltip: l10n.t('doctor.export_excel'),
                  icon: const Icon(Icons.file_download_outlined, size: 20),
                ),
              if (onImport != null)
                IconButton(
                  onPressed: onImport,
                  tooltip: l10n.t('doctor.import_excel'),
                  icon: const Icon(Icons.file_upload_outlined, size: 20),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _LatestValue extends StatelessWidget {
  const _LatestValue({required this.trend});

  final TrendData trend;

  @override
  Widget build(BuildContext context) {
    final TrendPoint last = trend.points.last;
    final MetricSeries series = trend.series;
    final bool critical = series.isCritical(last.value);
    final bool out = series.isOutOfRange(last.value);
    final Color color =
        critical ? AppColors.danger : (out ? AppColors.warning : AppColors.ok);

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(AppSpacing.radiusSm),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: <Widget>[
          Text(
            series.isPair
                ? Formatters.pair(last.value, last.valueSecondary, series.decimals)
                : Formatters.metric(last.value, series.decimals),
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: color,
            ),
          ),
          Text(
            Formatters.monthDay(last.at),
            style: TextStyle(fontSize: 11, color: color.withValues(alpha: 0.8)),
          ),
        ],
      ),
    );
  }
}

class _Chart extends StatelessWidget {
  const _Chart({required this.trend});

  final TrendData trend;

  @override
  Widget build(BuildContext context) {
    final MetricSeries series = trend.series;
    final List<TrendPoint> points = trend.points;

    final List<FlSpot> primary = <FlSpot>[
      for (int i = 0; i < points.length; i++) FlSpot(i.toDouble(), points[i].value),
    ];
    final List<FlSpot> secondary = series.isPair
        ? <FlSpot>[
            for (int i = 0; i < points.length; i++)
              if (points[i].valueSecondary != null)
                FlSpot(i.toDouble(), points[i].valueSecondary!),
          ]
        : <FlSpot>[];

    // Pad the axis so the target band and the line both stay inside the frame.
    final List<double> allValues = <double>[
      ...points.map((TrendPoint p) => p.value),
      ...points
          .where((TrendPoint p) => p.valueSecondary != null)
          .map((TrendPoint p) => p.valueSecondary!),
      if (series.targetMin != null) series.targetMin!,
      if (series.targetMax != null) series.targetMax!,
    ];
    final double minValue = allValues.reduce((double a, double b) => a < b ? a : b);
    final double maxValue = allValues.reduce((double a, double b) => a > b ? a : b);
    final double padding = ((maxValue - minValue).abs() * 0.15).clamp(0.5, 50);

    return LineChart(
      LineChartData(
        minY: minValue - padding,
        maxY: maxValue + padding,
        gridData: FlGridData(
          show: true,
          drawVerticalLine: false,
          getDrawingHorizontalLine: (double value) => FlLine(
            color: Theme.of(context).dividerColor.withValues(alpha: 0.6),
            strokeWidth: 1,
          ),
        ),
        borderData: FlBorderData(show: false),
        titlesData: FlTitlesData(
          topTitles: const AxisTitles(),
          rightTitles: const AxisTitles(),
          leftTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 38,
              getTitlesWidget: (double value, TitleMeta meta) => Text(
                value.toStringAsFixed(series.decimals > 1 ? 1 : 0),
                style: const TextStyle(
                  fontSize: 10,
                  color: AppColors.textTertiary,
                ),
              ),
            ),
          ),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 22,
              interval: (points.length / 4).ceilToDouble().clamp(1, 999),
              getTitlesWidget: (double value, TitleMeta meta) {
                final int index = value.round();
                if (index < 0 || index >= points.length) {
                  return const SizedBox.shrink();
                }
                return Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    Formatters.monthDay(points[index].at),
                    style: const TextStyle(
                      fontSize: 10,
                      color: AppColors.textTertiary,
                    ),
                  ),
                );
              },
            ),
          ),
        ),
        // The doctor's target range, drawn behind the data.
        rangeAnnotations: RangeAnnotations(
          horizontalRangeAnnotations: <HorizontalRangeAnnotation>[
            if (series.targetMin != null && series.targetMax != null)
              HorizontalRangeAnnotation(
                y1: series.targetMin!,
                y2: series.targetMax!,
                color: AppColors.ok.withValues(alpha: 0.10),
              ),
          ],
        ),
        lineTouchData: LineTouchData(
          touchTooltipData: LineTouchTooltipData(
            getTooltipItems: (List<LineBarSpot> spots) => spots
                .map(
                  (LineBarSpot spot) => LineTooltipItem(
                    '${Formatters.metric(spot.y, series.decimals)} ${series.unit}',
                    const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w600,
                      fontSize: 12,
                    ),
                  ),
                )
                .toList(),
          ),
        ),
        lineBarsData: <LineChartBarData>[
          LineChartBarData(
            spots: primary,
            isCurved: true,
            curveSmoothness: 0.25,
            color: AppColors.primary,
            barWidth: 2.4,
            dotData: FlDotData(
              show: points.length <= 40,
              getDotPainter: (FlSpot spot, double _, LineChartBarData __, int ___) {
                final bool critical = series.isCritical(spot.y);
                final bool out = series.isOutOfRange(spot.y);
                return FlDotCirclePainter(
                  radius: critical ? 4.5 : 3,
                  color: critical
                      ? AppColors.danger
                      : (out ? AppColors.warning : AppColors.primary),
                  strokeWidth: 0,
                );
              },
            ),
            belowBarData: BarAreaData(
              show: true,
              color: AppColors.primary.withValues(alpha: 0.08),
            ),
          ),
          if (secondary.isNotEmpty)
            LineChartBarData(
              spots: secondary,
              isCurved: true,
              curveSmoothness: 0.25,
              color: AppColors.accent,
              barWidth: 2,
              dashArray: <int>[5, 3],
              dotData: const FlDotData(show: false),
            ),
        ],
      ),
    );
  }
}

class _Stats extends StatelessWidget {
  const _Stats({required this.trend});

  final TrendData trend;

  @override
  Widget build(BuildContext context) {
    final AppLocalizations l10n = context.l10n;
    final int decimals = trend.series.decimals;

    return Row(
      children: <Widget>[
        if (trend.average != null)
          _Stat(
            label: l10n.t('chart.average'),
            value: Formatters.metric(trend.average!, decimals),
          ),
        if (trend.inTargetPercent != null)
          _Stat(
            label: l10n.t('chart.in_target'),
            value: '${trend.inTargetPercent!.toStringAsFixed(0)}%',
            color: trend.inTargetPercent! >= 70 ? AppColors.ok : AppColors.warning,
          ),
        if (trend.series.targetMin != null && trend.series.targetMax != null)
          _Stat(
            label: l10n.t('chart.target_range'),
            value: '${Formatters.metric(trend.series.targetMin!, decimals)}–'
                '${Formatters.metric(trend.series.targetMax!, decimals)}',
          ),
      ],
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value, this.color});

  final String label;
  final String value;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            label,
            style: const TextStyle(fontSize: 11, color: AppColors.textTertiary),
          ),
          const SizedBox(height: 2),
          Text(
            value,
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}
