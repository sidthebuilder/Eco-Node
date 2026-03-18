"use client"

import { useEffect, useState } from "react"
import Image from "next/image"
import { Globe } from "@/components/Globe"
import { KpiCard } from "@/components/KpiCard"
import { ForecastChart } from "@/components/ForecastChart"
import { JobForm } from "@/components/JobForm"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

interface JobData {
  id: string;
  name: string;
  status: string;
  current_region_id?: string;
  savings_usd: number;
  [key: string]: unknown;
}

interface MetricData {
  total_savings_usd: number;
  total_carbon_avoided_kgco2: number;
  total_migrations: number;
  total_jobs: number;
}

interface ForecastPoint {
  ts: string;
  carbon: number;
  carbon_lo: number;
  carbon_hi: number;
  price: number;
}

export default function Dashboard() {
  const [metrics, setMetrics] = useState<MetricData | null>(null)
  const [regions, setRegions] = useState<Record<string, unknown>>({})
  const [jobs, setJobs] = useState<JobData[]>([])
  const [decisions, setDecisions] = useState<Record<string, unknown>[]>([])
  const [forecast, setForecast] = useState<{ points: ForecastPoint[] }>({ points: [] })
  const [selectedRegion, setSelectedRegion] = useState("us-east1")
  const [apiError, setApiError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const fetchData = async () => {
    setIsLoading(true)
    setApiError(null)
    try {
      const [mRes, rRes, jRes, dRes] = await Promise.allSettled([
        fetch("http://localhost:8000/metrics"),
        fetch("http://localhost:8000/regions"),
        fetch("http://localhost:8000/jobs"),
        fetch("http://localhost:8000/decisions"),
      ])

      if (mRes.status === 'fulfilled' && mRes.value.ok) {
        setMetrics(await mRes.value.json())
      } else {
        console.warn('Failed to fetch metrics:', mRes.status === 'rejected' ? mRes.reason : mRes.value.status)
      }

      if (rRes.status === 'fulfilled' && rRes.value.ok) {
        const rData = await rRes.value.json()
        setRegions(rData)
        if (Object.keys(rData).length > 0 && !selectedRegion) {
          setSelectedRegion(Object.keys(rData)[0])
        }
      } else {
        console.warn('Failed to fetch regions:', rRes.status === 'rejected' ? rRes.reason : rRes.value.status)
      }

      if (jRes.status === 'fulfilled' && jRes.value.ok) {
        const jData = await jRes.value.json()
        setJobs((Object.values(jData) as JobData[]).filter((j) => !['DONE', 'FAILED'].includes(j.status)))
      } else {
        console.warn('Failed to fetch jobs:', jRes.status === 'rejected' ? jRes.reason : jRes.value.status)
      }

      if (dRes.status === 'fulfilled' && dRes.value.ok) {
        setDecisions(await dRes.value.json())
      } else {
        console.warn('Failed to fetch decisions:', dRes.status === 'rejected' ? dRes.reason : dRes.value.status)
      }
    } catch (error) {
      console.error('Error fetching data:', error)
      setApiError('Failed to connect to API. Is the backend running?')
    } finally {
      setIsLoading(false)
    }
  }

  const fetchForecast = async (regionId: string) => {
    if (!regionId) return
    try {
      const res = await fetch(`http://localhost:8000/forecast/${regionId}`)
      if (res.ok) setForecast(await res.json())
    } catch (e) {
      console.error(e)
    }
  }

  // Poll for live updates
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 5000)
    return () => clearInterval(interval)
  }, [])

  // Update forecast when region changes
  useEffect(() => {
    fetchForecast(selectedRegion)
  }, [selectedRegion])

  return (
    <div className="min-h-screen bg-background text-foreground p-8">
      <div className="max-w-7xl mx-auto space-y-8">

        {/* Error Banner */}
        {apiError && (
          <div className="bg-destructive/10 border border-destructive/20 text-destructive px-4 py-3 rounded-lg">
            <p className="font-medium">Connection Error</p>
            <p className="text-sm mt-1">{apiError}</p>
          </div>
        )}

        {/* Loading Indicator */}
        {isLoading && (
          <div className="bg-secondary/50 px-4 py-2 rounded-lg text-sm text-muted-foreground">
            Loading data...
          </div>
        )}

        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Image src="/logo.png" alt="EcoNode Logo" width={48} height={48} className="object-contain" />
            <div>
              <h1 className="text-3xl font-semibold tracking-tight">EcoNode</h1>
              <p className="text-muted-foreground mt-1">Intelligent Workload Placement</p>
            </div>
          </div>
          <div className="text-xs text-muted-foreground bg-secondary/50 px-3 py-1.5 rounded-full">
            Live Updates Active
          </div>
        </div>

        {/* KPIs */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <KpiCard
            title="Total Savings"
            metric={metrics ? `$${metrics.total_savings_usd.toFixed(2)}` : "$0.00"}
            trend="up"
          />
          <KpiCard
            title="Carbon Avoided"
            metric={metrics ? `${metrics.total_carbon_avoided_kgco2.toFixed(1)} kg` : "0 kg"}
            trend="up"
          />
          <KpiCard
            title="Active Jobs"
            metric={jobs.length.toString()}
            subtext={`${metrics?.total_migrations || 0} total migrations`}
          />
          <KpiCard
            title="Monitored Regions"
            metric={Object.keys(regions).length.toString()}
            subtext="Global coverage"
          />
        </div>

        {/* Main Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* Left Column (Wider) */}
          <div className="lg:col-span-2 space-y-6">
            <ForecastChart data={forecast.points} regionId={selectedRegion} />

            {/* Active Jobs Table */}
            <div className="rounded-xl border bg-card text-card-foreground shadow-sm">
              <div className="p-6">
                <h3 className="font-semibold tracking-tight">Active Workloads</h3>
                <p className="text-sm text-muted-foreground mb-4">Currently running or migrating jobs.</p>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Job Name</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Current Region</TableHead>
                      <TableHead className="text-right">Savings</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {jobs.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={4} className="text-center text-muted-foreground">
                          No active jobs
                        </TableCell>
                      </TableRow>
                    ) : (
                      jobs.map((job) => (
                        <TableRow key={job.id}>
                          <TableCell className="font-medium">{job.name}</TableCell>
                          <TableCell>
                            <Badge variant={job.status === 'RUNNING' ? 'default' : 'secondary'}>
                              {job.status}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {job.current_region_id || "PENDING"}
                          </TableCell>
                          <TableCell className="text-right text-emerald-500">
                            {job.savings_usd > 0 ? `+$${job.savings_usd.toFixed(2)}` : "-"}
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </div>
            </div>
          </div>

          {/* Right Column */}
          <div className="space-y-6">
            <div className="rounded-xl border bg-card text-card-foreground shadow-sm p-6 flex flex-col items-center justify-center">
              <h3 className="w-full text-left font-semibold tracking-tight mb-4">Global Network</h3>
              <Globe />
            </div>

            <JobForm onSubmitData={fetchData} />
          </div>

        </div>
      </div>
    </div>
  )
}
