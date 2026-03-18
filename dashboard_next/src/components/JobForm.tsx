"use client";

import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Loader2, Plus, Zap, Leaf } from "lucide-react";

export function JobForm({ onSubmitData }: { onSubmitData: () => void }) {
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [alpha, setAlpha] = useState(0.5);
    const [gpuType, setGpuType] = useState("h100");
    const [provider, setProvider] = useState("any");

    const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        setIsSubmitting(true);

        const formData = new FormData(e.currentTarget);
        const payload = {
            name: formData.get("name"),
            gpu_count: parseInt(formData.get("gpu_count") as string, 10),
            gpu_type: gpuType,
            duration_hours: parseFloat(formData.get("duration") as string),
            deadline_hours: parseFloat(formData.get("deadline") as string),
            budget_usd: parseFloat(formData.get("budget") as string),
            preferred_providers: provider === "any" ? [] : [provider],
            cost_weight: alpha,
            carbon_weight: 1.0 - alpha,
        };

        try {
            const res = await fetch("http://localhost:8000/jobs", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });

            if (res.ok) {
                onSubmitData();
            }
        } catch (error) {
            console.error(error);
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <Card className="p-6">
            <div className="mb-6">
                <h2 className="text-lg font-semibold tracking-tight">Schedule Job</h2>
                <p className="text-sm text-muted-foreground mt-1">
                    Configure computational requirements and routing preferences.
                </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-6">
                <div className="space-y-4">
                    <div className="grid gap-2">
                        <Label htmlFor="name">Job Name</Label>
                        <Input id="name" name="name" defaultValue="resnet-train-01" required />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div className="grid gap-2">
                            <Label htmlFor="gpu_type">Hardware Type</Label>
                            <Select value={gpuType} onValueChange={setGpuType}>
                                <SelectTrigger>
                                    <SelectValue placeholder="Select GPU" />
                                </SelectTrigger>
                                <SelectContent className="max-h-60">
                                    <SelectItem disabled value="separator-1" className="font-semibold text-muted-foreground opacity-100">NVIDIA Hopper & Blackwell Series</SelectItem>
                                    <SelectItem value="gb200">NVIDIA GB200 (Grace Blackwell)</SelectItem>
                                    <SelectItem value="b200">NVIDIA B200</SelectItem>
                                    <SelectItem value="h200">NVIDIA H200 (141GB)</SelectItem>
                                    <SelectItem value="h100">NVIDIA H100 (80GB)</SelectItem>

                                    <SelectItem disabled value="separator-2" className="mt-2 font-semibold text-muted-foreground opacity-100">NVIDIA Ampere Series</SelectItem>
                                    <SelectItem value="a100-80">NVIDIA A100 (80GB)</SelectItem>
                                    <SelectItem value="a100-40">NVIDIA A100 (40GB)</SelectItem>
                                    <SelectItem value="a10g">NVIDIA A10G / A10</SelectItem>

                                    <SelectItem disabled value="separator-3" className="mt-2 font-semibold text-muted-foreground opacity-100">NVIDIA Ada Lovelace & Volta</SelectItem>
                                    <SelectItem value="l40s">NVIDIA L40S</SelectItem>
                                    <SelectItem value="l4">NVIDIA L4</SelectItem>
                                    <SelectItem value="v100">NVIDIA V100</SelectItem>

                                    <SelectItem disabled value="separator-4" className="mt-2 font-semibold text-muted-foreground opacity-100">Inference & Specialty</SelectItem>
                                    <SelectItem value="t4">NVIDIA T4</SelectItem>
                                    <SelectItem value="tpu-v5p">Google TPU v5p</SelectItem>
                                    <SelectItem value="tpu-v4">Google TPU v4</SelectItem>
                                    <SelectItem value="amd-mi300x">AMD Instinct MI300X</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="grid gap-2">
                            <Label htmlFor="provider">Preferred Provider</Label>
                            <Select value={provider} onValueChange={setProvider}>
                                <SelectTrigger>
                                    <SelectValue placeholder="Any Provider" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="any">Any Provider</SelectItem>
                                    <SelectItem value="aws">Amazon Web Services</SelectItem>
                                    <SelectItem value="gcp">Google Cloud Platform</SelectItem>
                                    <SelectItem value="azure">Microsoft Azure</SelectItem>
                                    <SelectItem value="onprem">On-Premises Data Center</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div className="grid gap-2">
                            <Label htmlFor="gpu_count">GPUs Required</Label>
                            <Input
                                id="gpu_count"
                                name="gpu_count"
                                type="number"
                                min="1"
                                max="1024"
                                defaultValue="8"
                                required
                            />
                        </div>
                        <div className="grid gap-2">
                            <Label htmlFor="duration">Duration (hrs)</Label>
                            <Input
                                id="duration"
                                name="duration"
                                type="number"
                                step="0.5"
                                min="0.5"
                                defaultValue="4"
                                required
                            />
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div className="grid gap-2">
                            <Label htmlFor="deadline">Deadline (hrs)</Label>
                            <Input
                                id="deadline"
                                name="deadline"
                                type="number"
                                step="1"
                                min="1"
                                defaultValue="24"
                                required
                            />
                        </div>
                        <div className="grid gap-2">
                            <Label htmlFor="budget">Budget ($)</Label>
                            <Input
                                id="budget"
                                name="budget"
                                type="number"
                                step="1"
                                min="1"
                                defaultValue="100"
                                required
                            />
                        </div>
                    </div>

                    <div className="space-y-4 pt-2">
                        <div className="flex justify-between items-center text-sm font-medium">
                            <div className="flex items-center gap-2 text-rose-500">
                                <Zap className="h-4 w-4" />
                                <span>Cost: {alpha.toFixed(2)}</span>
                            </div>
                            <div className="text-muted-foreground">Optimization Weights</div>
                            <div className="flex items-center gap-2 text-emerald-500">
                                <span>Carbon: {(1 - alpha).toFixed(2)}</span>
                                <Leaf className="h-4 w-4" />
                            </div>
                        </div>
                        <Slider
                            value={[alpha]}
                            max={1}
                            step={0.05}
                            onValueChange={(val) => setAlpha(val[0])}
                            className="py-4"
                        />
                    </div>
                </div>

                <Button type="submit" className="w-full" disabled={isSubmitting}>
                    {isSubmitting ? (
                        <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            Submitting...
                        </>
                    ) : (
                        <>
                            <Plus className="mr-2 h-4 w-4" />
                            Initialize Job
                        </>
                    )}
                </Button>
            </form>
        </Card>
    );
}
