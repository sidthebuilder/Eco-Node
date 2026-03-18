"use client";

import { Card } from "@/components/ui/card";
import { AreaChart } from "@tremor/react";

interface ForecastData {
    ts: string;
    carbon: number;
    price: number;
}

interface ForecastChartProps {
    data: ForecastData[];
    regionId: string;
}

export function ForecastChart({ data, regionId }: ForecastChartProps) {
    // Format data for Tremor
    const chartData = data.map((d) => ({
        time: new Date(d.ts).toLocaleTimeString("en-US", {
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
        }),
        "Carbon (gCO₂/kWh)": d.carbon,
        "Price ($/hr)": d.price,
    }));

    const valueFormatter = (number: number) => {
        return Intl.NumberFormat("us").format(number).toString();
    };

    return (
        <Card className="p-6">
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h3 className="text-sm font-medium text-muted-foreground">
                        Forecast ({regionId || "Select a Region"})
                    </h3>
                    <p className="text-xs text-muted-foreground mt-1">
                        Carbon vs Price over next 24h
                    </p>
                </div>
            </div>

            {chartData.length > 0 ? (
                <AreaChart
                    className="h-72 mt-4"
                    data={chartData}
                    index="time"
                    categories={["Carbon (gCO₂/kWh)", "Price ($/hr)"]}
                    colors={["emerald", "slate"]}
                    valueFormatter={valueFormatter}
                    yAxisWidth={60}
                    showAnimation={true}
                />
            ) : (
                <div className="h-72 flex items-center justify-center border border-dashed rounded-lg mt-4">
                    <p className="text-sm text-muted-foreground">Waiting for region data...</p>
                </div>
            )}
        </Card>
    );
}
