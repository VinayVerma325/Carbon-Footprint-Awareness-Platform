// State variables
const USER_ID = "demo_user_123";
let latestCalculations = null;
let isFetchingRoute = false;
let showAllHistory = false;

// API endpoint helper — always same-origin, served by our own FastAPI
// backend. No client-side Google Maps key, no user-configurable backend
// URL: the browser only ever talks to our server at /api/*, which holds
// the real key server-side (.env). See services/google_services.py.
function getApiUrl(endpoint) {
    return endpoint;
}


// Client-side Database Fallback (localStorage)
const LocalDatabase = {
    getLogs: function() {
        const stored = localStorage.getItem("carbonwise_logs");
        return stored ? JSON.parse(stored) : [];
    },
    saveLog: function(log) {
        const logs = this.getLogs();
        logs.push(log);
        localStorage.setItem("carbonwise_logs", JSON.stringify(logs));
    },
    getActions: function() {
        const stored = localStorage.getItem("carbonwise_actions");
        return stored ? JSON.parse(stored) : [];
    },
    saveAction: function(action) {
        const actions = this.getActions();
        actions.push(action);
        localStorage.setItem("carbonwise_actions", JSON.stringify(actions));
    }
};

// Client-side Carbon Calculator Logic
const CarbonCalculator = {
    ELECTRICITY_CO2_PER_KWH: 0.385,
    NATURAL_GAS_CO2_PER_CUBIC_METER: 2.03,
    TRANSPORT_FACTORS: {
        petrol_car: 0.404,
        diesel_car: 0.380,
        hybrid_car: 0.200,
        electric_car: 0.050,
        motorcycle: 0.180,
        bus: 0.100,
        train: 0.050,
        flight_short: 0.250,
        flight_long: 0.150,
        bicycle: 0.0,
        bike: 0.0,
        walk: 0.0,
    },
    DIET_FACTORS: {
        heavy_meat: 9.0,
        average: 6.8,
        no_beef: 5.2,
        vegetarian: 4.7,
        vegan: 4.1
    },
    WASTE_LANDFILL_FACTOR: 0.500,
    WASTE_RECYCLE_FACTOR: 0.050,

    calculateTotal: function(inputs) {
        const electricity_usage = parseFloat(inputs.electricity_kwh) || 0;
        const gas_usage = parseFloat(inputs.gas_m3) || 0;
        const transport_logs = inputs.transport || [];
        const diet_type = inputs.diet_type || "average";
        const diet_days = parseInt(inputs.diet_days) || 1;
        const waste_kg = parseFloat(inputs.waste_kg) || 0;
        const waste_recycling_rate = parseFloat(inputs.waste_recycling_rate) || 0.0;

        const electricity_co2 = parseFloat((electricity_usage * this.ELECTRICITY_CO2_PER_KWH).toFixed(3));
        const gas_co2 = parseFloat((gas_usage * this.NATURAL_GAS_CO2_PER_CUBIC_METER).toFixed(3));

        let transport_co2 = 0;
        transport_logs.forEach(log => {
            const dist = parseFloat(log.distance) || 0;
            const mode = log.mode || "car";
            const vtype = log.vehicle_type || "petrol";
            
            let factor_key = mode.toLowerCase();
            if (factor_key === "car" && vtype) {
                factor_key = `${vtype.toLowerCase()}_car`;
            } else if (factor_key === "flight") {
                factor_key = dist < 300 ? "flight_short" : "flight_long";
            }
            
            const factor = this.TRANSPORT_FACTORS[factor_key] || this.TRANSPORT_FACTORS["petrol_car"];
            transport_co2 += dist * factor;
        });
        transport_co2 = parseFloat(transport_co2.toFixed(3));

        const diet_factor = this.DIET_FACTORS[diet_type.toLowerCase()] || this.DIET_FACTORS["average"];
        const diet_co2 = parseFloat((diet_days * diet_factor).toFixed(3));

        const recycled_weight = waste_kg * waste_recycling_rate;
        const landfill_weight = waste_kg - recycled_weight;
        const waste_co2 = parseFloat(((landfill_weight * this.WASTE_LANDFILL_FACTOR) + (recycled_weight * this.WASTE_RECYCLE_FACTOR)).toFixed(3));

        const total = parseFloat((electricity_co2 + gas_co2 + transport_co2 + diet_co2 + waste_co2).toFixed(3));

        return {
            electricity_co2,
            gas_co2,
            transport_co2,
            diet_co2,
            waste_co2,
            total_co2: total
        };
    }
};

// Client-side Recommendation Engine Logic
const RecommendationEngine = {
    TARGET_DAILY_LIMITS: {
        electricity: 2.5,
        gas: 1.5,
        transport: 3.0,
        diet: 4.5,
        waste: 0.2
    },
    analyzeAndRecommend: function(userData, historicalLogs) {
        const averages = {
            electricity: 0,
            gas: 0,
            transport: 0,
            diet: 0,
            waste: 0
        };

        if (historicalLogs && historicalLogs.length > 0) {
            const numLogs = historicalLogs.length;
            historicalLogs.forEach(log => {
                averages.electricity += parseFloat(log.electricity_co2) || 0;
                averages.gas += parseFloat(log.gas_co2) || 0;
                averages.transport += parseFloat(log.transport_co2) || 0;
                averages.diet += parseFloat(log.diet_co2) || 0;
                averages.waste += parseFloat(log.waste_co2) || 0;
            });
            Object.keys(averages).forEach(k => {
                averages[k] /= numLogs;
            });
        } else {
            const currentCo2 = CarbonCalculator.calculateTotal(userData);
            averages.electricity = currentCo2.electricity_co2;
            averages.gas = currentCo2.gas_co2;
            averages.transport = currentCo2.transport_co2;
            averages.diet = currentCo2.diet_co2;
            averages.waste = currentCo2.waste_co2;
        }

        const recommendations = [];

        // Check Transport
        if (averages.transport > this.TARGET_DAILY_LIMITS.transport) {
            const excess = averages.transport - this.TARGET_DAILY_LIMITS.transport;
            const savings = parseFloat((excess * 0.6).toFixed(2));
            recommendations.push({
                category: "transport",
                title: "Optimize Transit Choices",
                description: "Your transportation footprint is high. Consider carpooling, switching to public transit or an EV, or using eco-routing on Google Maps.",
                impact: excess > 5.0 ? "High" : "Medium",
                estimated_savings_kg: savings
            });
        }

        // Check Electricity
        if (averages.electricity > this.TARGET_DAILY_LIMITS.electricity) {
            const excess = averages.electricity - this.TARGET_DAILY_LIMITS.electricity;
            const savings = parseFloat((excess * 0.3).toFixed(2));
            recommendations.push({
                category: "electricity",
                title: "Improve Home Energy Efficiency",
                description: "Your household electricity consumption exceeds green baselines. Transition to LED bulbs, install smart thermostats, and unplug idle electronics.",
                impact: excess > 4.0 ? "High" : "Medium",
                estimated_savings_kg: savings
            });
        }

        // Check Diet
        if (averages.diet > this.TARGET_DAILY_LIMITS.diet) {
            const excess = averages.diet - this.TARGET_DAILY_LIMITS.diet;
            const savings = parseFloat((excess * 0.4).toFixed(2));
            recommendations.push({
                category: "diet",
                title: "Incorporate Plant-Based Options",
                description: "Diet emissions are elevated. Replacing red meat with plant-based alternatives or implementing 'Meatless Mondays' yields high carbon savings.",
                impact: excess < 3.0 ? "Medium" : "High",
                estimated_savings_kg: savings
            });
        }

        // Check Waste
        if (averages.waste > this.TARGET_DAILY_LIMITS.waste) {
            const excess = averages.waste - this.TARGET_DAILY_LIMITS.waste;
            const savings = parseFloat((excess * 0.8).toFixed(2));
            recommendations.push({
                category: "waste",
                title: "Enhance Recycling & Composting",
                description: "Your landfill waste output is high. Set up structured sorting for recyclables, compost food scraps, and purchase items with minimal packaging.",
                impact: excess > 0.5 ? "Medium" : "Low",
                estimated_savings_kg: savings
            });
        }

        if (recommendations.length === 0) {
            recommendations.push({
                category: "general",
                title: "Maintain Your Green Habits!",
                description: "Outstanding work! Your carbon footprint is well within sustainable target limits. Keep tracking and sharing your tips with others.",
                impact: "Low",
                estimated_savings_kg: 0.0
            });
        }

        recommendations.sort((a, b) => b.estimated_savings_kg - a.estimated_savings_kg);
        return recommendations;
    }
};

// Dom Elements
const form = document.getElementById("footprint-form");
const tabBtns = document.querySelectorAll(".tab-btn");
const tabPanels = document.querySelectorAll(".tab-panel");
const transportModeSelect = document.getElementById("transport-mode");
const vehicleTypeGroup = document.getElementById("vehicle-type-group");
const calcRouteBtn = document.getElementById("calc-route-btn");
const routeOriginInput = document.getElementById("route-origin");
const routeDestInput = document.getElementById("route-dest");
const routeResultDiv = document.getElementById("route-result");
const distanceInput = document.getElementById("distance");
const distanceUnitSelect = document.getElementById("distance-unit");
const distanceInputLabel = document.getElementById("distance-input-label");

// Distance Unit Switch handler (miles <-> km)
if (distanceUnitSelect) {
    distanceUnitSelect.addEventListener("change", () => {
        const unit = distanceUnitSelect.value;
        const distanceVal = parseFloat(distanceInput.value) || 0;
        
        if (unit === "km") {
            distanceInputLabel.textContent = "Distance Traveled (km)";
            // Convert miles to km
            distanceInput.value = (distanceVal * 1.60934).toFixed(1);
        } else {
            distanceInputLabel.textContent = "Distance Traveled (miles)";
            // Convert km to miles
            distanceInput.value = (distanceVal * 0.621371).toFixed(1);
        }
    });
}

// Metrics DOM
const totalCo2Value = document.getElementById("total-co2-value");
const totalCo2Ring = document.getElementById("total-co2-ring");
const energyCo2Val = document.getElementById("energy-co2");
const transportCo2Val = document.getElementById("transport-co2");
const dietCo2Val = document.getElementById("diet-co2");
const wasteCo2Val = document.getElementById("waste-co2");

// Progress fills
const energyBar = document.getElementById("energy-bar");
const transportBar = document.getElementById("transport-bar");
const dietBar = document.getElementById("diet-bar");
const wasteBar = document.getElementById("waste-bar");

const targetAssessment = document.getElementById("target-assessment");
const recommendationsContainer = document.getElementById("recommendations-container");
const historyTbody = document.getElementById("history-tbody");
const ariaAnnounce = document.getElementById("aria-announcement");

// Set active tabs
tabBtns.forEach(btn => {
    btn.addEventListener("click", (e) => {
        e.preventDefault();
        tabBtns.forEach(b => {
            b.classList.remove("active");
            b.setAttribute("aria-selected", "false");
        });
        tabPanels.forEach(p => {
            p.classList.remove("active");
            p.setAttribute("hidden", "true");
        });

        btn.classList.add("active");
        btn.setAttribute("aria-selected", "true");
        const targetId = btn.getAttribute("aria-controls");
        const targetPanel = document.getElementById(targetId);
        targetPanel.classList.add("active");
        targetPanel.removeAttribute("hidden");
        targetPanel.focus();
    });
});

// Hide vehicle type selector if transportation mode is not personal car
transportModeSelect.addEventListener("change", () => {
    const mode = transportModeSelect.value;
    if (mode === "car" || mode === "motorcycle") {
        vehicleTypeGroup.style.display = "block";
        vehicleTypeGroup.removeAttribute("aria-hidden");
    } else {
        vehicleTypeGroup.style.display = "none";
        vehicleTypeGroup.setAttribute("aria-hidden", "true");
    }
});

// Google Routes API integration through FastAPI backend
calcRouteBtn.addEventListener("click", async () => {
    if (isFetchingRoute) return;

    const origin = routeOriginInput.value.trim();
    const destination = routeDestInput.value.trim();
    const mode = transportModeSelect.value;
    
    if (!origin || !destination) {
        routeResultDiv.className = "route-feedback error";
        routeResultDiv.textContent = "Please provide both Origin and Destination addresses.";
        announceToScreenReader("Please provide both Origin and Destination addresses.");
        return;
    }

    try {
        isFetchingRoute = true;
        calcRouteBtn.disabled = true;
        calcRouteBtn.textContent = "Calculating route...";
        routeResultDiv.className = "route-feedback info";
        routeResultDiv.textContent = "Calculating route...";
        announceToScreenReader("Calculating route distance.");

        // Always call our own backend. It holds the Google Maps API key
        // server-side (.env) and returns its own clearly-labeled
        // simulated_fallback result if no key is configured — see
        // services/google_services.py. The browser never sees a Maps API key.
        const response = await fetch(getApiUrl("/api/route"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ origin, destination, travel_mode: mode })
        });

        if (!response.ok) {
            const errBody = await response.json().catch(() => ({}));
            throw new Error(errBody.detail || `Server error ${response.status}`);
        }

        const data = await response.json();
        const miles = data.distance_miles;
        const unit = distanceUnitSelect ? distanceUnitSelect.value : "miles";
        const isFallback = data.source && (data.source.includes("simulate") || data.source.includes("fallback"));
        
        if (unit === "km") {
            const km = parseFloat((miles * 1.60934).toFixed(2));
            distanceInput.value = km;
            if (isFallback) {
                routeResultDiv.className = "route-feedback warning";
                routeResultDiv.innerHTML = `⚠️ Estimated distance (live Google Maps routing isn't configured on this server). Distance: <strong>${km} km</strong>.<br><small style="margin-top: 0.25rem; display: block; opacity: 0.9;">This is a placeholder, not a real route. Site owner: set GOOGLE_MAPS_API_KEY in .env to enable live routing.</small>`;
            } else {
                routeResultDiv.className = "route-feedback success";
                routeResultDiv.textContent = `Route estimated! Distance: ${km} km. Source: ${data.source.replace(/_/g, ' ')}.`;
            }
            announceToScreenReader(`Route estimated successfully. Calculated distance is ${km} kilometers.`);
        } else {
            distanceInput.value = miles;
            if (isFallback) {
                routeResultDiv.className = "route-feedback warning";
                routeResultDiv.innerHTML = `⚠️ Estimated distance (live Google Maps routing isn't configured on this server). Distance: <strong>${miles} miles</strong>.<br><small style="margin-top: 0.25rem; display: block; opacity: 0.9;">This is a placeholder, not a real route. Site owner: set GOOGLE_MAPS_API_KEY in .env to enable live routing.</small>`;
            } else {
                routeResultDiv.className = "route-feedback success";
                routeResultDiv.textContent = `Route estimated! Distance: ${miles} miles. Source: ${data.source.replace(/_/g, ' ')}.`;
            }
            announceToScreenReader(`Route estimated successfully. Calculated distance is ${miles} miles.`);
        }
        
        // Dispatch change event to trigger re-calculations if needed
        distanceInput.dispatchEvent(new Event("change"));

    } catch (err) {
        console.error("Route calculation error", err);
        routeResultDiv.className = "route-feedback error";
        routeResultDiv.textContent = `Could not calculate route: ${err.message}. Make sure the CarbonWise server is running (python main.py) and reload the page.`;
        announceToScreenReader(`Route calculation failed. ${err.message}.`);
    } finally {
        isFetchingRoute = false;
        calcRouteBtn.disabled = false;
        calcRouteBtn.textContent = "Estimate Distance";
    }
});

// Form Submission to log carbon footprint
form.addEventListener("submit", async (e) => {
    e.preventDefault();
    
    // Gather input fields
    const rawDistance = parseFloat(distanceInput.value) || 0;
    const unit = distanceUnitSelect ? distanceUnitSelect.value : "miles";
    const distanceInMiles = unit === "km" ? rawDistance * 0.621371 : rawDistance;

    const inputData = {
        electricity_kwh: parseFloat(document.getElementById("electricity").value) || 0,
        gas_m3: parseFloat(document.getElementById("gas").value) || 0,
        transport: [
            {
                distance: distanceInMiles,
                mode: transportModeSelect.value,
                vehicle_type: vehicleTypeGroup.style.display !== "none" ? document.getElementById("vehicle-type").value : null
            }
        ],
        diet_type: document.getElementById("diet-type").value,
        diet_days: 1, // log single day
        waste_kg: parseFloat(document.getElementById("waste-kg").value) || 0,
        waste_recycling_rate: (parseFloat(document.getElementById("recycling-rate").value) || 0) / 100
    };

    const payload = {
        user_id: USER_ID,
        ...inputData
    };

    let calcs = null;
    let success = false;
    try {
        const response = await fetch(getApiUrl("/api/calculate"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        if (response.ok) {
            const result = await response.json();
            calcs = result.calculations;
            success = true;
        }
    } catch (err) {
        console.warn("Backend API `/api/calculate` not reachable. Performing local calculation.", err);
    }

    if (!success) {
        calcs = CarbonCalculator.calculateTotal(payload);
        const localLog = {
            timestamp: new Date().toISOString(),
            ...calcs,
            inputs: inputData
        };
        LocalDatabase.saveLog(localLog);
        success = true;
    }
    
    if (success && calcs) {
        latestCalculations = calcs;
        updateKPIs(latestCalculations);
        await fetchDashboardState();
        announceToScreenReader(`Successfully logged daily footprint. Total today is ${latestCalculations.total_co2} kg CO2.`);
    }
});

// Form Reset handler
const resetBtn = document.getElementById("reset-form-btn");
if (resetBtn) {
    resetBtn.addEventListener("click", () => {
        // Reset standard inputs
        document.getElementById("electricity").value = "5.0";
        document.getElementById("gas").value = "0.0";
        document.getElementById("transport-mode").value = "car";
        document.getElementById("transport-mode").dispatchEvent(new Event("change"));
        document.getElementById("vehicle-type").value = "petrol";
        
        // Clear route estimator inputs and results
        document.getElementById("route-origin").value = "";
        document.getElementById("route-dest").value = "";
        const routeResult = document.getElementById("route-result");
        routeResult.className = "route-feedback";
        routeResult.textContent = "";
        routeResult.style.display = "none";
        
        // Reset distance based on active unit
        const unit = distanceUnitSelect ? distanceUnitSelect.value : "miles";
        document.getElementById("distance").value = unit === "km" ? "16.1" : "10.0";
        
        // Reset diet type
        document.getElementById("diet-type").value = "average";
        
        // Reset waste
        document.getElementById("waste-kg").value = "1.5";
        document.getElementById("recycling-rate").value = "30";
        
        // Switch back to first tab (Energy)
        const firstTab = document.getElementById("tab-energy");
        if (firstTab) {
            firstTab.click();
        }
        
        announceToScreenReader("Form inputs have been reset to defaults.");
    });
}

// Action Buttons Logging
document.querySelectorAll(".action-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
        const action = btn.getAttribute("data-action");
        const offset = parseFloat(btn.getAttribute("data-offset"));
        const title = btn.querySelector(".title").textContent;

        let success = false;
        try {
            const response = await fetch(getApiUrl("/api/action"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    user_id: USER_ID,
                    action: action,
                    title: title,
                    carbon_offset_kg: offset,
                    timestamp: new Date().toISOString()
                })
            });

            if (response.ok) {
                success = true;
            }
        } catch (err) {
            console.warn("Backend API `/api/action` not reachable. Saving green action locally.", err);
        }

        if (!success) {
            const localAction = {
                action: action,
                title: title,
                carbon_offset_kg: offset,
                timestamp: new Date().toISOString()
            };
            LocalDatabase.saveAction(localAction);
            success = true;
        }

        if (success) {
            announceToScreenReader(`Logged green habit: ${title}. Offset of ${offset} kg CO2 credited.`);
            await fetchDashboardState();
        }
    });
});

// Helper to update progress ring & KPI details
function updateKPIs(calc, offsetVal = 0) {
    const rawTotal = calc.total_co2;
    const netTotal = Math.max(0, rawTotal - offsetVal);
    totalCo2Value.textContent = netTotal.toFixed(1);
    
    // Limit scale to 30kg for the dashboard ring
    const maxVal = 25.0;
    const percentage = Math.min((netTotal / maxVal), 1.0);
    
    // Circumference of radius 70 is 2 * pi * 70 = 439.82
    const offset = 439.82 - (percentage * 439.82);
    totalCo2Ring.style.strokeDashoffset = offset;

    // Set color state based on emissions levels
    if (netTotal > 15) {
        totalCo2Ring.style.stroke = "#ef4444"; // red
    } else if (netTotal > 8) {
        totalCo2Ring.style.stroke = "#f59e0b"; // yellow
    } else {
        totalCo2Ring.style.stroke = "url(#emerald-gradient)"; // emerald
    }

    // Update category texts
    energyCo2Val.textContent = `${calc.electricity_co2 + calc.gas_co2} kg`;
    transportCo2Val.textContent = `${calc.transport_co2} kg`;
    dietCo2Val.textContent = `${calc.diet_co2} kg`;
    wasteCo2Val.textContent = `${calc.waste_co2} kg`;

    // Update sub-category progress bars
    energyBar.style.width = `${Math.min((calc.electricity_co2 + calc.gas_co2) / 6 * 100, 100)}%`;
    transportBar.style.width = `${Math.min(calc.transport_co2 / 6 * 100, 100)}%`;
    dietBar.style.width = `${Math.min(calc.diet_co2 / 10 * 100, 100)}%`;
    wasteBar.style.width = `${Math.min(calc.waste_co2 / 2 * 100, 100)}%`;

    // Assessment message
    let assessment = "";
    let sustainableDiff = netTotal - 11.5;
    if (sustainableDiff > 5.0) {
        assessment = `<span class="badge danger">Above Average</span> Your footprint is high. Try optimizing transit and home heating.`;
    } else if (sustainableDiff > 0) {
        assessment = `<span class="badge warning">Moderate</span> You are close to the national target of 11.5 kg. A few smart offsets will get you there!`;
    } else {
        assessment = `<span class="badge success">Sustainable</span> Great job! Your footprint is under the sustainable daily limit.`;
    }
    if (offsetVal > 0) {
        assessment += ` <span class="badge info">Offset Applied</span> Applied -${offsetVal.toFixed(1)} kg CO₂ from daily green actions.`;
    }
    targetAssessment.innerHTML = assessment;
}

// Fetch user history & recommendations in parallel
async function fetchDashboardState() {
    const logsPromise = fetch(getApiUrl(`/api/logs?user_id=${USER_ID}`))
        .then(r => r.ok ? r.json() : Promise.reject())
        .catch(() => {
            console.warn("Backend API `/api/logs` not reachable. Using localStorage.");
            return LocalDatabase.getLogs();
        });

    const recsPromise = fetch(getApiUrl(`/api/recommendations?user_id=${USER_ID}`))
        .then(r => r.ok ? r.json() : Promise.reject())
        .catch(() => {
            console.warn("Backend API `/api/recommendations` not reachable. Using client-side logic.");
            return null;
        });

    const actionsPromise = fetch(getApiUrl(`/api/action?user_id=${USER_ID}`))
        .then(r => r.ok ? r.json() : Promise.reject())
        .catch(() => {
            console.warn("Backend API `/api/action` not reachable. Using localStorage.");
            return LocalDatabase.getActions();
        });

    const [logsData, serverRecsData, actionsData] = await Promise.all([logsPromise, recsPromise, actionsPromise]);

    const todayStr = new Date().toISOString().slice(0, 10);
    
    // Calculate total green offsets for today
    const todayActions = actionsData.filter(act => {
        try {
            return act.timestamp && act.timestamp.slice(0, 10) === todayStr;
        } catch(e) { return false; }
    });
    const totalOffset = todayActions.reduce((sum, act) => sum + (parseFloat(act.carbon_offset_kg) || 0), 0);

    // Render green actions table
    const actionsTbody = document.getElementById("actions-tbody");
    if (actionsTbody) {
        actionsTbody.innerHTML = "";
        const displayActions = showAllHistory ? actionsData : todayActions;
        
        if (displayActions.length === 0) {
            const tr = document.createElement("tr");
            tr.innerHTML = `<td colspan="3" class="empty-table">No green actions logged ${showAllHistory ? 'yet' : 'today'}.</td>`;
            actionsTbody.appendChild(tr);
        } else {
            displayActions.slice().reverse().forEach(act => {
                const dateStr = new Date(act.timestamp).toLocaleString();
                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td>${dateStr}</td>
                    <td><strong>${act.title || act.action}</strong></td>
                    <td style="color: var(--primary); font-weight: 500;">-${parseFloat(act.carbon_offset_kg).toFixed(1)} kg CO₂</td>
                `;
                actionsTbody.appendChild(tr);
            });
        }
    }

    if (logsData.length > 0) {
        // Filter to today's logs only, unless "Show All" is toggled
        let displayLogs = logsData;
        if (!showAllHistory) {
            displayLogs = logsData.filter(log => {
                try {
                    return log.timestamp && log.timestamp.slice(0, 10) === todayStr;
                } catch(e) { return false; }
            });
        }

        // Render history table
        historyTbody.innerHTML = "";
        if (displayLogs.length === 0) {
            const tr = document.createElement("tr");
            tr.innerHTML = `<td colspan="6" class="empty-table">No logs for today. Submit a daily log to start tracking.</td>`;
            historyTbody.appendChild(tr);
        } else {
            displayLogs.slice().reverse().forEach(log => {
                const dateStr = new Date(log.timestamp).toLocaleString();
                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td>${dateStr}</td>
                    <td><strong>${log.total_co2.toFixed(2)} kg</strong></td>
                    <td>${(log.electricity_co2 + log.gas_co2).toFixed(2)} kg</td>
                    <td>${log.transport_co2.toFixed(2)} kg</td>
                    <td>${log.diet_co2.toFixed(2)} kg</td>
                    <td>${log.waste_co2.toFixed(2)} kg</td>
                `;
                historyTbody.appendChild(tr);
            });
        }

        // Update metrics KPI with the most recent log
        const latest = logsData[logsData.length - 1];
        updateKPIs(latest, totalOffset);
    }

    let recsData = serverRecsData;
    if (!recsData) {
        const defaultInputs = {
            electricity_kwh: 5.0,
            gas_m3: 0.0,
            transport: [{ distance: 10.0, mode: "car", vehicle_type: "petrol" }],
            diet_type: "average",
            waste_kg: 1.5,
            waste_recycling_rate: 0.3
        };
        const latestLog = logsData.length > 0 ? logsData[logsData.length - 1] : null;
        const inputData = latestLog ? latestLog.inputs : defaultInputs;
        recsData = RecommendationEngine.analyzeAndRecommend(inputData, logsData);
    }

    if (recsData && recsData.length > 0) {
        recommendationsContainer.innerHTML = "";
        recsData.forEach(rec => {
            const card = document.createElement("div");
            card.className = "rec-card";
            card.setAttribute("role", "article");
            
            let categoryIcon = `<svg width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="M2 22c1.25-6.7 5.85-11.3 12.5-12.5C20.2 8.3 22 2 22 2s-6.3 1.8-12.5 7.5C3.8 15.1.7 20.75 2 22z"></path><path d="M9 13l3 3M12 10l3 3"></path></svg>`;
            if (rec.category === "transport") {
                categoryIcon = `<svg width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><rect x="4" y="2" width="16" height="16" rx="2" ry="2"></rect><line x1="4" y1="14" x2="20" y2="14"></line><line x1="8" y1="6" x2="16" y2="6"></line><line x1="6" y1="18" x2="6" y2="21"></line><line x1="18" y1="18" x2="18" y2="21"></line><circle cx="8" cy="10" r="1"></circle><circle cx="16" cy="10" r="1"></circle></svg>`;
            } else if (rec.category === "electricity") {
                categoryIcon = `<svg width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>`;
            } else if (rec.category === "diet") {
                categoryIcon = `<svg width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="M2 22c1.25-6.7 5.85-11.3 12.5-12.5C20.2 8.3 22 2 22 2s-6.3 1.8-12.5 7.5C3.8 15.1.7 20.75 2 22z"></path><path d="M9 13l3 3M12 10l3 3"></path></svg>`;
            } else if (rec.category === "waste") {
                categoryIcon = `<svg width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>`;
            }

            card.innerHTML = `
                <div class="rec-icon" aria-hidden="true">${categoryIcon}</div>
                <div class="rec-content">
                    <div class="rec-header">
                        <h3>${rec.title}</h3>
                        <span class="impact-badge ${rec.impact.toLowerCase()}">${rec.impact} Impact</span>
                    </div>
                    <p>${rec.description}</p>
                    <span class="rec-savings">Potential monthly savings: <strong>${rec.estimated_savings_kg} kg CO₂</strong></span>
                </div>
            `;
            recommendationsContainer.appendChild(card);
        });
    }
}

// Accessibility screen reader announcement helper
function announceToScreenReader(message) {
    ariaAnnounce.textContent = message;
    setTimeout(() => {
        ariaAnnounce.textContent = "";
    }, 3000);
}

// Appearance Customizer (Theme + Accent Color + Font Size + Compact Mode)
const appearanceToggleBtn = document.getElementById("appearance-toggle-btn");
const appearanceDropdown = document.getElementById("appearance-dropdown");

if (appearanceToggleBtn && appearanceDropdown) {
    appearanceToggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const isExpanded = appearanceToggleBtn.getAttribute("aria-expanded") === "true";
        appearanceToggleBtn.setAttribute("aria-expanded", !isExpanded);
        appearanceDropdown.classList.toggle("show");
        appearanceDropdown.hidden = isExpanded;
        appearanceDropdown.setAttribute("aria-hidden", isExpanded);
    });

    // Close dropdown when clicking outside
    document.addEventListener("click", (e) => {
        if (appearanceDropdown.classList.contains("show") && !appearanceDropdown.contains(e.target) && !appearanceToggleBtn.contains(e.target)) {
            appearanceToggleBtn.setAttribute("aria-expanded", "false");
            appearanceDropdown.classList.remove("show");
            appearanceDropdown.hidden = true;
            appearanceDropdown.setAttribute("aria-hidden", "true");
        }
    });
}

const themeBtns = document.querySelectorAll(".theme-btn");
const accentDots = document.querySelectorAll(".accent-dot");
const fontsizeBtns = document.querySelectorAll(".fontsize-btn");
const compactToggle = document.getElementById("compact-toggle");
const accentNameDisplay = document.getElementById("accent-name-display");
const fontsizePreview = document.getElementById("fontsize-preview-text");

const accentNames = {
    "#10b981": "Emerald",
    "#0ea5e9": "Ocean Blue",
    "#f59e0b": "Sunset Amber",
    "#a855f7": "Royal Purple",
    "#f43f5e": "Rose"
};

// Load saved appearance settings
const savedTheme = localStorage.getItem("carbonwise_theme") || "dark";
const savedAccent = localStorage.getItem("carbonwise_accent") || "#10b981";
const savedFontSize = localStorage.getItem("carbonwise_fontsize") || "medium";
const savedCompact = localStorage.getItem("carbonwise_compact") === "true";

applyTheme(savedTheme);
applyAccent(savedAccent);
applyFontSize(savedFontSize);
applyCompact(savedCompact);
if (compactToggle) compactToggle.checked = savedCompact;

// Theme Toggle handlers
themeBtns.forEach(btn => {
    btn.addEventListener("click", () => {
        const theme = btn.getAttribute("data-theme");
        applyTheme(theme);
        localStorage.setItem("carbonwise_theme", theme);
        announceToScreenReader(`Theme switched to ${theme} mode.`);
    });
});

// Accent Color Toggle handlers
accentDots.forEach(dot => {
    dot.addEventListener("click", () => {
        const color = dot.getAttribute("data-accent");
        applyAccent(color);
        localStorage.setItem("carbonwise_accent", color);
        announceToScreenReader(`Accent color changed to ${accentNames[color] || color}.`);
    });
});

// Font Size handlers
fontsizeBtns.forEach(btn => {
    btn.addEventListener("click", () => {
        const size = btn.getAttribute("data-size");
        applyFontSize(size);
        localStorage.setItem("carbonwise_fontsize", size);
        announceToScreenReader(`Font size changed to ${size}.`);
    });
});

// Compact Mode toggle
if (compactToggle) {
    compactToggle.addEventListener("change", () => {
        applyCompact(compactToggle.checked);
        localStorage.setItem("carbonwise_compact", compactToggle.checked);
        announceToScreenReader(compactToggle.checked ? "Compact mode enabled." : "Compact mode disabled.");
    });
}

function applyTheme(theme) {
    document.body.classList.remove("light-theme", "glass-theme");
    themeBtns.forEach(b => {
        b.classList.remove("active");
        b.setAttribute("aria-checked", "false");
    });
    
    const selectedBtn = document.querySelector(`.theme-btn[data-theme="${theme}"]`);
    if (selectedBtn) {
        selectedBtn.classList.add("active");
        selectedBtn.setAttribute("aria-checked", "true");
    }

    if (theme === "light") {
        document.body.classList.add("light-theme");
    } else if (theme === "glass") {
        document.body.classList.add("glass-theme");
    }
}

function applyAccent(color) {
    accentDots.forEach(d => {
        d.classList.remove("active");
        d.setAttribute("aria-checked", "false");
    });
    const activeDot = document.querySelector(`.accent-dot[data-accent="${color}"]`);
    if (activeDot) {
        activeDot.classList.add("active");
        activeDot.setAttribute("aria-checked", "true");
    }
    if (accentNameDisplay) accentNameDisplay.textContent = accentNames[color] || "Custom";

    // Update primary theme color variables dynamically on the document root
    document.documentElement.style.setProperty("--primary", color);
    
    // Generate a slightly brighter hover color dynamically
    const hoverMap = {
        "#10b981": "#34d399",
        "#0ea5e9": "#38bdf8",
        "#f59e0b": "#fbbf24",
        "#a855f7": "#c084fc",
        "#f43f5e": "#fb7185"
    };
    document.documentElement.style.setProperty("--primary-hover", hoverMap[color] || color);
}

function applyFontSize(size) {
    document.body.classList.remove("font-small", "font-large");
    fontsizeBtns.forEach(b => {
        b.classList.remove("active");
        b.setAttribute("aria-pressed", "false");
    });
    const selectedBtn = document.querySelector(`.fontsize-btn[data-size="${size}"]`);
    if (selectedBtn) {
        selectedBtn.classList.add("active");
        selectedBtn.setAttribute("aria-pressed", "true");
    }
    if (size === "small") {
        document.body.classList.add("font-small");
        if (fontsizePreview) fontsizePreview.style.fontSize = "0.8rem";
    } else if (size === "large") {
        document.body.classList.add("font-large");
        if (fontsizePreview) fontsizePreview.style.fontSize = "1.3rem";
    } else {
        if (fontsizePreview) fontsizePreview.style.fontSize = "1rem";
    }
}

function applyCompact(isCompact) {
    if (isCompact) {
        document.body.classList.add("compact-mode");
    } else {
        document.body.classList.remove("compact-mode");
    }
}

// Toggle History (Today vs All)
const toggleHistoryBtn = document.getElementById("toggle-history-btn");
if (toggleHistoryBtn) {
    toggleHistoryBtn.addEventListener("click", async () => {
        showAllHistory = !showAllHistory;
        toggleHistoryBtn.textContent = showAllHistory ? "Today Only" : "Show All";
        await fetchDashboardState();
    });
}

// Clear History
const clearHistoryBtn = document.getElementById("clear-history-btn");
if (clearHistoryBtn) {
    clearHistoryBtn.addEventListener("click", async () => {
        if (!confirm("Are you sure you want to clear all calculation history? This cannot be undone.")) return;

        // Clear server-side logs
        try {
            await fetch(getApiUrl(`/api/logs?user_id=${USER_ID}`), { method: "DELETE" });
        } catch (err) {
            console.warn("Backend DELETE /api/logs not reachable.", err);
        }

        // Clear client-side logs
        localStorage.removeItem("carbonwise_logs");
        localStorage.removeItem("carbonwise_actions");

        // Reset UI
        historyTbody.innerHTML = `<tr><td colspan="6" class="empty-table">No calculation history available. Log a footprint to populate.</td></tr>`;
        announceToScreenReader("All calculation history has been cleared.");
        await fetchDashboardState();
    });
}

// Initial setup on load
window.addEventListener("DOMContentLoaded", async () => {
    // Setup default values
    updateKPIs({
        electricity_co2: 1.92,
        gas_co2: 0.0,
        transport_co2: 4.04,
        diet_co2: 6.8,
        waste_co2: 0.53,
        total_co2: 13.29
    });
    await fetchDashboardState();
});
