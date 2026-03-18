"use client";

import { Card } from "@/components/ui/card";
import { TrendingDown, TrendingUp } from "lucide-react";

interface KpiCardProps {
    title: string;
    metric: string;
    subtext?: string;
    trend?: "up" | "down" | "neutral";
}

export function KpiCard({ title, metric, subtext, trend }: KpiCardProps) {
    return (
        <Card className="p-6">
            <div className="flex flex-col gap-1">
                <h3 className="text-sm font-medium text-muted-foreground">{title}</h3>
                <p className="text-3xl font-semibold tracking-tight">{metric}</p>
                {subtext && (
                    <div className="flex items-center gap-1 mt-1 text-sm">
                        {trend === "up" && <TrendingUp className="w-4 h-4 text-emerald-500" />}
                        {trend === "down" && <TrendingDown className="w-4 h-4 text-rose-500" />}
                        <span
                            className={
                                trend === "up"
                                    ? "text-emerald-500"
                                    : trend === "down"
                                        ? "text-rose-500"
                                        : "text-muted-foreground"
                            }
                        >
                            {subtext}
                        </span>
                    </div>
                )}
            </div>
        </Card>
    );
}
