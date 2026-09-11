/*
 * Licensed to The Apereo Foundation under one or more contributor license
 * agreements. See the NOTICE file distributed with this work for
 * additional information regarding copyright ownership.
 *
 * The Apereo Foundation licenses this file to you under the Apache License,
 * Version 2.0 (the "License"); you may not use this file except in
 * compliance with the License. You may obtain a copy of the License at:
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *
 * See the License for the specific language governing permissions and
 * limitations under the License.
 * 
 */
package org.unitime.timetable.api.connectors;

import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import org.apache.commons.logging.Log;
import org.dom4j.Document;
import org.dom4j.DocumentHelper;
import org.dom4j.Element;
import org.springframework.stereotype.Service;
import org.unitime.timetable.ApplicationProperties;
import org.unitime.timetable.api.ApiConnector;
import org.unitime.timetable.api.ApiHelper;
import org.unitime.timetable.api.JsonApiHelper;
import org.unitime.timetable.dataexchange.DataExchangeHelper;
import org.unitime.timetable.model.DistributionPref;
import org.unitime.timetable.model.Session;
import org.unitime.timetable.security.rights.Right;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

/**
 * UniTime AI Smart Ingestion Backend Connector.
 * Transforms incoming structured JSON payloads (curriculum, course offerings,
 * class schedules, instructors, time/room preferences, and distribution constraints)
 * into UniTime native DataExchange XML documents and imports them transactionally.
 * 
 * @author Hanafi Shiddiq / Tomas Muller
 */
@Service("/api/smart-ingest")
public class SmartIngestConnector extends ApiConnector {

	private String safeGetString(JsonObject obj, String key, String defaultValue) {
		if (obj == null || !obj.has(key) || obj.get(key).isJsonNull()) return defaultValue;
		return obj.get(key).getAsString().trim();
	}

	private int safeGetInt(JsonObject obj, String key, int defaultValue) {
		if (obj == null || !obj.has(key) || obj.get(key).isJsonNull()) return defaultValue;
		return obj.get(key).getAsInt();
	}

	private boolean safeGetBoolean(JsonObject obj, String key, boolean defaultValue) {
		if (obj == null || !obj.has(key) || obj.get(key).isJsonNull()) return defaultValue;
		return obj.get(key).getAsBoolean();
	}

	private float safeGetFloat(JsonObject obj, String key, float defaultValue) {
		if (obj == null || !obj.has(key) || obj.get(key).isJsonNull()) return defaultValue;
		return obj.get(key).getAsFloat();
	}


	@Override
	protected ApiHelper createHelper(HttpServletRequest request, HttpServletResponse response) {
		return new JsonApiHelper(request, response, sessionContext, getCacheMode());
	}

	@Override
	protected String getName() {
		return "smart-ingest";
	}

	@Override
	public void doGet(ApiHelper helper) throws IOException {
		helper.getSessionContext().checkPermissionAnyAuthority(Right.ApiDataExchangeConnector);

		Map<String, Object> metadata = new LinkedHashMap<String, Object>();
		metadata.put("name", "UniTime AI Smart Ingestion API");
		metadata.put("version", "1.0");
		metadata.put("endpoint", "/api/smart-ingest");
		metadata.put("status", "UP");
		metadata.put("description", "High-performance academic data ingestion endpoint transforming AI-extracted JSON curriculum & timetabling payloads into UniTime native offerings and preference structures.");
		metadata.put("schema", "https://unitime.org/schema/v1/unitime-smart-ingest-schema.json");

		Map<String, String> aliasMappings = new LinkedHashMap<String, String>();
		aliasMappings.put("CANNOT_OVERLAP", "DIFF_TIME");
		aliasMappings.put("SAME_INSTRUCTOR", "SAME_INSTR");
		aliasMappings.put("DIFF_INSTRUCTOR", "DIFF_INSTR");
		aliasMappings.put("BACK_TO_BACK", "BTB");
		aliasMappings.put("MEET_TOGETHER", "MEET_WITH");
		aliasMappings.put("PRECEDENCE", "PRECEDENCE");
		aliasMappings.put("BTB_PRECEDENCE", "BTB_PRECEDENCE");
		aliasMappings.put("SPREAD_DAYS", "SPREAD");
		aliasMappings.put("AT_MOST_2_HOURS_APART", "NHB(2)");
		aliasMappings.put("SAME_ROOM", "SAME_ROOM");
		aliasMappings.put("SAME_DAYS", "SAME_DAYS");
		aliasMappings.put("SAME_TIME", "SAME_TIME");
		aliasMappings.put("SAME_START", "SAME_START");
		aliasMappings.put("SAME_STUDENTS", "SAME_STUDENTS");
		aliasMappings.put("CAN_SHARE_ROOM", "CAN_SHARE_ROOM");
		metadata.put("supportedConstraintAliases", aliasMappings);

		List<String> supportedMethods = new ArrayList<String>();
		supportedMethods.add("POST (Execute Smart Ingest)");
		supportedMethods.add("GET (API Metadata & Schema Specification)");
		metadata.put("supportedMethods", supportedMethods);

		helper.setResponse(metadata);
	}

	@Override
	public void doPost(ApiHelper helper) throws IOException {
		helper.getSessionContext().checkPermissionAnyAuthority(Right.ApiDataExchangeConnector);

		final List<LogEntry> logEntries = new ArrayList<LogEntry>();
		final AtomicInteger errorCount = new AtomicInteger(0);
		final AtomicInteger warnCount = new AtomicInteger(0);
		Log log = createLogListener(logEntries, errorCount, warnCount);
		
		boolean offeringsImportSuccess = false;
		boolean preferencesImportSuccess = false;
		String errorMessage = null;
		JsonObject rootJson = null;

		org.hibernate.Session hibSession = new org.unitime.timetable.model.dao._RootDAO().getSession();
		org.hibernate.Transaction tx = null;
		try {
			rootJson = helper.getRequest(JsonObject.class);
			if (rootJson == null || rootJson.isJsonNull()) {
				throw new IllegalArgumentException("Empty or invalid JSON payload received.");
			}

			validatePayload(rootJson);

			JsonObject academicSession = rootJson.getAsJsonObject("academicSession");
			String year = safeGetString(academicSession, "year", "");
			String term = safeGetString(academicSession, "term", "");
			String campus = safeGetString(academicSession, "campus", "");

			Session session = Session.getSessionUsingInitiativeYearTerm(campus, year, term);
			if (session == null) {
				throw new IllegalArgumentException("Academic session not found for campus: '" + campus + "', year: '" + year + "', term: '" + term + "'.");
			}
			ApplicationProperties.setSessionId(session.getSessionId());

			String userId = helper.getSessionContext().isAuthenticated() ? helper.getSessionContext().getUser().getExternalUserId() : null;

			tx = hibSession.beginTransaction();

			Document offeringsDoc = buildOfferingsDocument(rootJson);
			Document prefDoc = buildPreferencesDocument(rootJson);

			log.info("Starting UniTime Smart Ingest for Academic Session: " + term + " " + year + " (" + campus + ")");
			DataExchangeHelper.importDocument(offeringsDoc, userId, log);
			offeringsImportSuccess = true;

			if (prefDoc != null && hasPreferencesContent(prefDoc)) {
				log.info("Importing Distribution & Preference constraints...");
				DataExchangeHelper.importDocument(prefDoc, userId, log);
				preferencesImportSuccess = true;
			}
			
			tx.commit();
			
			IngestResponse response = buildResponse(rootJson, offeringsImportSuccess, preferencesImportSuccess, errorCount.get(), warnCount.get(), errorMessage, logEntries);
			helper.setResponse(response);
		} catch (Exception e) {
			errorMessage = e.getMessage();
			log.error("Ingestion failed: " + e.getMessage(), e);
			errorCount.incrementAndGet();
			
			if (rootJson != null) {
				IngestResponse response = buildResponse(rootJson, offeringsImportSuccess, preferencesImportSuccess, errorCount.get(), warnCount.get(), errorMessage, logEntries);
				helper.setResponse(response);
			} else {
				helper.sendError(HttpServletResponse.SC_BAD_REQUEST, e);
			}
		} finally {
			if (tx != null && tx.isActive()) {
				try { tx.rollback(); } catch (Exception ignored) {}
			}
		}
	}

	protected void validatePayload(JsonObject rootJson) {
		if (!rootJson.has("academicSession") || !rootJson.get("academicSession").isJsonObject()) {
			throw new IllegalArgumentException("Missing required 'academicSession' component.");
		}
		JsonObject academicSession = rootJson.getAsJsonObject("academicSession");
		if (!academicSession.has("year") || safeGetString(academicSession, "year", "").isEmpty()) {
			throw new IllegalArgumentException("Missing required 'academicSession.year' property.");
		}
		if (!academicSession.has("term") || safeGetString(academicSession, "term", "").isEmpty()) {
			throw new IllegalArgumentException("Missing required 'academicSession.term' property.");
		}
		if (!academicSession.has("campus") || safeGetString(academicSession, "campus", "").isEmpty()) {
			throw new IllegalArgumentException("Missing required 'academicSession.campus' property.");
		}

		if (!rootJson.has("department") || !rootJson.get("department").isJsonObject()) {
			throw new IllegalArgumentException("Missing required 'department' component.");
		}
		JsonObject department = rootJson.getAsJsonObject("department");
		if (!department.has("code") || safeGetString(department, "code", "").isEmpty()) {
			throw new IllegalArgumentException("Missing required 'department.code' property.");
		}

		if (!rootJson.has("subjectArea") || !rootJson.get("subjectArea").isJsonObject()) {
			throw new IllegalArgumentException("Missing required 'subjectArea' component.");
		}
		JsonObject subjectArea = rootJson.getAsJsonObject("subjectArea");
		if (!subjectArea.has("abbreviation") || safeGetString(subjectArea, "abbreviation", "").isEmpty()) {
			throw new IllegalArgumentException("Missing required 'subjectArea.abbreviation' property.");
		}

		if (!rootJson.has("courses") || !rootJson.get("courses").isJsonArray() || rootJson.getAsJsonArray("courses").size() == 0) {
			throw new IllegalArgumentException("Missing or empty required 'courses' array.");
		}
	}

	protected Document buildOfferingsDocument(JsonObject rootJson) {
		Document doc = DocumentHelper.createDocument();

		JsonObject academicSession = rootJson.getAsJsonObject("academicSession");
		String year = safeGetString(academicSession, "year", "").trim();
		String term = safeGetString(academicSession, "term", "").trim();
		String campus = safeGetString(academicSession, "campus", "").trim();

		String mode = "incremental";
		if (rootJson.has("ingestControl") && rootJson.get("ingestControl").isJsonObject()) {
			JsonObject ingestControl = rootJson.getAsJsonObject("ingestControl");
			if (ingestControl.has("mode")) {
				mode = safeGetString(ingestControl, "mode", "incremental");
			}
		}
		boolean incremental = !"full_replace".equalsIgnoreCase(mode);

		JsonObject subjectArea = rootJson.getAsJsonObject("subjectArea");
		String subjAbbv = safeGetString(subjectArea, "abbreviation", "");

		Element offeringsEl = doc.addElement("offerings");
		offeringsEl.addAttribute("year", year);
		offeringsEl.addAttribute("term", term);
		offeringsEl.addAttribute("campus", campus);
		offeringsEl.addAttribute("incremental", incremental ? "true" : "false");
		offeringsEl.addAttribute("dateFormat", "yyyy/M/d");
		offeringsEl.addAttribute("timeFormat", "HHmm");
		offeringsEl.addAttribute("created", new SimpleDateFormat("yyyy/MM/dd HH:mm:ss", Locale.US).format(new Date()));

		JsonArray coursesArray = rootJson.getAsJsonArray("courses");
		java.util.Set<String> seenCourses = new java.util.HashSet<String>();
		for (JsonElement courseElem : coursesArray) {
			if (!courseElem.isJsonObject()) continue;
			JsonObject courseObj = courseElem.getAsJsonObject();

			String courseNbr = safeGetString(courseObj, "courseNumber", "");
			String courseId = subjAbbv + "_" + courseNbr;
			if (!seenCourses.add(courseId)) {
				throw new IllegalArgumentException("Duplicate course offering detected in payload: " + courseId);
			}
			String title = safeGetString(courseObj, "title", "");
			boolean controlling = safeGetBoolean(courseObj, "controlling", true);
			String scheduleBookNote = safeGetString(courseObj, "scheduleBookNote", null);
			int projectedDemand = safeGetInt(courseObj, "projectedDemand", 0);
			String consentType = safeGetString(courseObj, "consentType", null);

			Element offeringEl = offeringsEl.addElement("offering");
			offeringEl.addAttribute("id", subjAbbv + "_" + courseNbr);
			offeringEl.addAttribute("offered", "true");
			offeringEl.addAttribute("action", "insert");

			Element courseEl = offeringEl.addElement("course");
			courseEl.addAttribute("subject", subjAbbv);
			courseEl.addAttribute("courseNbr", courseNbr);
			if (!title.isEmpty()) {
				courseEl.addAttribute("title", title);
			}
			courseEl.addAttribute("controlling", controlling ? "true" : "false");
			if (scheduleBookNote != null && !scheduleBookNote.isEmpty()) {
				courseEl.addAttribute("scheduleBookNote", scheduleBookNote);
			}
			if (projectedDemand > 0) {
				courseEl.addAttribute("reserved", String.valueOf(projectedDemand));
			}
			if (consentType != null && !consentType.isEmpty() && !"None".equalsIgnoreCase(consentType)) {
				Element consentEl = courseEl.addElement("consent");
				consentEl.addAttribute("type", consentType);
			}

			if (courseObj.has("credit") && courseObj.get("credit").isJsonObject()) {
				JsonObject creditObj = courseObj.getAsJsonObject("credit");
				Element creditEl = courseEl.addElement("courseCredit");

				String format = safeGetString(creditObj, "format", "fixedUnit");
				String creditType = safeGetString(creditObj, "creditType", "collegiate");
				String creditUnitType = safeGetString(creditObj, "creditUnitType", "sks");

				creditEl.addAttribute("creditFormat", format);
				creditEl.addAttribute("creditType", creditType);
				creditEl.addAttribute("creditUnitType", creditUnitType);
				creditEl.addAttribute("fractionalCreditAllowed", "true");

				if ("fixedUnit".equalsIgnoreCase(format) || creditObj.has("units")) {
					if (creditObj.has("units")) {
						creditEl.addAttribute("fixedCredit", String.valueOf(safeGetFloat(creditObj, "units", 0f)));
					}
				}
				if (creditObj.has("minimumUnits")) {
					creditEl.addAttribute("minimumCredit", String.valueOf(safeGetFloat(creditObj, "minimumUnits", 0f)));
				}
				if (creditObj.has("maximumUnits")) {
					creditEl.addAttribute("maximumCredit", String.valueOf(safeGetFloat(creditObj, "maximumUnits", 0f)));
				}
			}

			if (courseObj.has("configurations") && courseObj.get("configurations").isJsonArray()) {
				JsonArray configsArray = courseObj.getAsJsonArray("configurations");
				for (JsonElement configElem : configsArray) {
					if (!configElem.isJsonObject()) continue;
					JsonObject configObj = configElem.getAsJsonObject();

					String configName = safeGetString(configObj, "name", "Default");
					String durationType = safeGetString(configObj, "durationType", "MIN_PER_WEEK");
					String instructionalMethod = safeGetString(configObj, "instructionalMethod", null);

					int configCapacitySum = calculateConfigCapacity(configObj);
					int configLimit = configCapacitySum > 0 ? configCapacitySum : (projectedDemand > 0 ? projectedDemand : 0);

					Element configEl = offeringEl.addElement("config");
					configEl.addAttribute("name", configName);
					configEl.addAttribute("limit", String.valueOf(configLimit));
					if (durationType != null && !durationType.isEmpty()) {
						configEl.addAttribute("durationType", durationType);
					}
					if (instructionalMethod != null && !instructionalMethod.isEmpty()) {
						configEl.addAttribute("instructionalMethod", instructionalMethod);
					}

					buildSubpartsHierarchy(configEl, configObj);
					buildClassesHierarchy(configEl, configObj);
				}
			}
		}

		return doc;
	}

	protected int calculateConfigCapacity(JsonObject configObj) {
		int sum = 0;
		if (configObj.has("subparts") && configObj.get("subparts").isJsonArray()) {
			JsonArray subparts = configObj.getAsJsonArray("subparts");
			if (subparts.size() > 0 && subparts.get(0).isJsonObject()) {
				JsonObject firstSubpart = subparts.get(0).getAsJsonObject();
				if (firstSubpart.has("classes") && firstSubpart.get("classes").isJsonArray()) {
					for (JsonElement classElem : firstSubpart.getAsJsonArray("classes")) {
						if (classElem.isJsonObject()) {
							JsonObject classObj = classElem.getAsJsonObject();
							if (classObj.has("capacity") && !classObj.get("capacity").isJsonNull()) {
								sum += classObj.get("capacity").getAsInt();
							}
						}
					}
				}
			}
		}
		return sum;
	}

	protected void buildSubpartsHierarchy(Element configEl, JsonObject configObj) {
		if (!configObj.has("subparts") || !configObj.get("subparts").isJsonArray()) return;
		JsonArray subparts = configObj.getAsJsonArray("subparts");

		Map<String, Element> subpartElements = new HashMap<String, Element>();
		List<JsonObject> deferredSubparts = new ArrayList<JsonObject>();

		for (JsonElement subpartElem : subparts) {
			if (!subpartElem.isJsonObject()) continue;
			JsonObject subpartObj = subpartElem.getAsJsonObject();
			String type = translateInstructionalType(safeGetString(subpartObj, "type", "Lecture"));
			int minPerWeek = safeGetInt(subpartObj, "minPerWeek", 0);
			String suffix = safeGetString(subpartObj, "suffix", null);
			String parentType = translateInstructionalType(safeGetString(subpartObj, "parentSubpartType", null));

			if (parentType == null || parentType.isEmpty()) {
				Element subpartEl = configEl.addElement("subpart");
				subpartEl.addAttribute("type", type);
				subpartEl.addAttribute("minPerWeek", String.valueOf(minPerWeek));
				if (suffix != null && !suffix.isEmpty()) {
					subpartEl.addAttribute("suffix", suffix);
				}
				subpartElements.put(type, subpartEl);
				if (suffix != null && !suffix.isEmpty()) {
					subpartElements.put(type + "_" + suffix, subpartEl);
				}
			} else {
				deferredSubparts.add(subpartObj);
			}
		}

		for (JsonObject subpartObj : deferredSubparts) {
			String type = translateInstructionalType(safeGetString(subpartObj, "type", "Lecture"));
			int minPerWeek = safeGetInt(subpartObj, "minPerWeek", 0);
			String suffix = safeGetString(subpartObj, "suffix", null);
			String parentType = translateInstructionalType(safeGetString(subpartObj, "parentSubpartType", ""));

			Element parentEl = subpartElements.get(parentType);
			Element subpartEl;
			if (parentEl != null) {
				subpartEl = parentEl.addElement("subpart");
			} else {
				subpartEl = configEl.addElement("subpart");
			}
			subpartEl.addAttribute("type", type);
			subpartEl.addAttribute("minPerWeek", String.valueOf(minPerWeek));
			if (suffix != null && !suffix.isEmpty()) {
				subpartEl.addAttribute("suffix", suffix);
			}
			subpartElements.put(type, subpartEl);
			if (suffix != null && !suffix.isEmpty()) {
				subpartElements.put(type + "_" + suffix, subpartEl);
			}
		}
	}

	protected void buildClassesHierarchy(Element configEl, JsonObject configObj) {
		if (!configObj.has("subparts") || !configObj.get("subparts").isJsonArray()) return;
		JsonArray subparts = configObj.getAsJsonArray("subparts");

		Map<String, Element> classElements = new HashMap<String, Element>();
		List<ClassNode> deferredClasses = new ArrayList<ClassNode>();

		for (JsonElement subpartElem : subparts) {
			if (!subpartElem.isJsonObject()) continue;
			JsonObject subpartObj = subpartElem.getAsJsonObject();
			String subpartType = translateInstructionalType(safeGetString(subpartObj, "type", "Lecture"));

			if (subpartObj.has("classes") && subpartObj.get("classes").isJsonArray()) {
				for (JsonElement classElem : subpartObj.getAsJsonArray("classes")) {
					if (!classElem.isJsonObject()) continue;
					JsonObject classObj = classElem.getAsJsonObject();
					String sectionName = safeGetString(classObj, "sectionName", "01");
					String parentSection = safeGetString(classObj, "parentClassSection", null);

					if (parentSection == null || parentSection.isEmpty()) {
						Element classEl = createClassElement(configEl, classObj, subpartType, sectionName);
						classElements.put(sectionName, classEl);
					} else {
						deferredClasses.add(new ClassNode(classObj, subpartType, sectionName, parentSection));
					}
				}
			}
		}

		for (ClassNode node : deferredClasses) {
			Element parentEl = classElements.get(node.parentSection);
			Element classEl;
			if (parentEl != null) {
				classEl = createClassElement(parentEl, node.classObj, node.subpartType, node.sectionName);
			} else {
				classEl = createClassElement(configEl, node.classObj, node.subpartType, node.sectionName);
			}
			classElements.put(node.sectionName, classEl);
		}
	}

	protected Element createClassElement(Element parentEl, JsonObject classObj, String subpartType, String sectionName) {
		Element classEl = parentEl.addElement("class");
		classEl.addAttribute("suffix", sectionName);
		classEl.addAttribute("type", subpartType);

		int capacity = safeGetInt(classObj, "capacity", 40);
		classEl.addAttribute("limit", String.valueOf(capacity));

		if (classObj.has("roomRatio")) {
			classEl.addAttribute("roomRatio", String.valueOf(safeGetFloat(classObj, "roomRatio", 1.0f)));
		}
		if (classObj.has("scheduleNote") && !safeGetString(classObj, "scheduleNote", "").isEmpty()) {
			classEl.addAttribute("scheduleNote", safeGetString(classObj, "scheduleNote", ""));
		}
		if (classObj.has("cancelled") && safeGetBoolean(classObj, "cancelled", false)) {
			classEl.addAttribute("cancelled", "true");
		}
		if (classObj.has("splitAttendance") && safeGetBoolean(classObj, "splitAttendance", false)) {
			classEl.addAttribute("splitAttendance", "true");
		}

		if (classObj.has("timePreferences") && classObj.get("timePreferences").isJsonArray()) {
			JsonArray timePrefs = classObj.getAsJsonArray("timePreferences");
			if (timePrefs.size() > 0) {
				JsonObject tpObj = timePrefs.get(0).getAsJsonObject();
				if (tpObj.has("days") && tpObj.has("startTime") && tpObj.has("endTime")) {
					Element timeEl = classEl.addElement("time");
					timeEl.addAttribute("days", normalizeDays(safeGetString(tpObj, "days", "")));
					timeEl.addAttribute("startTime", normalizeTime(safeGetString(tpObj, "startTime", "")));
					timeEl.addAttribute("endTime", normalizeTime(safeGetString(tpObj, "endTime", "")));
				}
			}
		}

		if (classObj.has("roomPreferences") && classObj.get("roomPreferences").isJsonArray()) {
			for (JsonElement rpElem : classObj.getAsJsonArray("roomPreferences")) {
				if (!rpElem.isJsonObject()) continue;
				JsonObject rpObj = rpElem.getAsJsonObject();
				if (rpObj.has("building") && rpObj.has("roomNumber")) {
					Element roomEl = classEl.addElement("room");
					roomEl.addAttribute("building", safeGetString(rpObj, "building", ""));
					roomEl.addAttribute("roomNbr", safeGetString(rpObj, "roomNumber", ""));
				}
			}
		}

		if (classObj.has("instructors") && classObj.get("instructors").isJsonArray()) {
			for (JsonElement instrElem : classObj.getAsJsonArray("instructors")) {
				if (!instrElem.isJsonObject()) continue;
				JsonObject instrObj = instrElem.getAsJsonObject();
				if (!instrObj.has("id")) continue;

				Element instrEl = classEl.addElement("instructor");
				instrEl.addAttribute("id", safeGetString(instrObj, "id", ""));

				if (instrObj.has("name")) {
					ParsedName pn = parseName(safeGetString(instrObj, "name", ""));
					if (pn.firstName != null && !pn.firstName.isEmpty()) {
						instrEl.addAttribute("fname", pn.firstName);
					}
					if (pn.middleName != null && !pn.middleName.isEmpty()) {
						instrEl.addAttribute("mname", pn.middleName);
					}
					if (pn.lastName != null && !pn.lastName.isEmpty()) {
						instrEl.addAttribute("lname", pn.lastName);
					}
					if (pn.title != null && !pn.title.isEmpty()) {
						instrEl.addAttribute("title", pn.title);
					}
				}

				boolean isLead = safeGetBoolean(instrObj, "isLead", false);
				instrEl.addAttribute("lead", isLead ? "true" : "false");

				int share = safeGetInt(instrObj, "sharePercentage", 100);
				instrEl.addAttribute("share", String.valueOf(share));
			}
		}

		return classEl;
	}

	protected Document buildPreferencesDocument(JsonObject rootJson) {
		Document doc = DocumentHelper.createDocument();

		JsonObject academicSession = rootJson.getAsJsonObject("academicSession");
		String year = safeGetString(academicSession, "year", "").trim();
		String term = safeGetString(academicSession, "term", "").trim();
		String campus = safeGetString(academicSession, "campus", "").trim();

		JsonObject department = rootJson.getAsJsonObject("department");
		String deptCode = safeGetString(department, "code", "");

		JsonObject subjectArea = rootJson.getAsJsonObject("subjectArea");
		String subjAbbv = safeGetString(subjectArea, "abbreviation", "");

		Element prefRoot = doc.addElement("preferences");
		prefRoot.addAttribute("year", year);
		prefRoot.addAttribute("term", term);
		prefRoot.addAttribute("campus", campus);
		prefRoot.addAttribute("dateFormat", "yyyy/M/d");
		prefRoot.addAttribute("timeFormat", "HHmm");
		prefRoot.addAttribute("created", new SimpleDateFormat("yyyy/MM/dd HH:mm:ss", Locale.US).format(new Date()));

		Element deptEl = prefRoot.addElement("department");
		deptEl.addAttribute("code", deptCode);

		if (rootJson.has("distributionConstraints") && rootJson.get("distributionConstraints").isJsonArray()) {
			JsonArray constraintsArray = rootJson.getAsJsonArray("distributionConstraints");
			for (JsonElement dcElem : constraintsArray) {
				if (!dcElem.isJsonObject()) continue;
				JsonObject dcObj = dcElem.getAsJsonObject();

				String rawType = safeGetString(dcObj, "type", "DIFF_TIME");
				String mappedType = translateConstraintType(rawType);
				String rawLevel = safeGetString(dcObj, "level", "REQUIRED");
				String mappedLevel = translatePreferenceLevel(rawLevel);
				String rawStructure = safeGetString(dcObj, "structure", "AllClasses");
				String structure = translateDistributionStructure(rawStructure);
				String note = safeGetString(dcObj, "note", null);
				String constraintCourseNumber = safeGetString(dcObj, "courseNumber", null);

				Element distPrefEl = deptEl.addElement("distributionPref");
				distPrefEl.addAttribute("type", mappedType);
				distPrefEl.addAttribute("level", mappedLevel);
				distPrefEl.addAttribute("structure", structure);

				if (dcObj.has("classes") && dcObj.get("classes").isJsonArray()) {
					for (JsonElement classRefElem : dcObj.getAsJsonArray("classes")) {
						if (!classRefElem.isJsonObject()) continue;
						JsonObject classRef = classRefElem.getAsJsonObject();
						String cCourse = safeGetString(classRef, "courseNumber", constraintCourseNumber);
						String cSection = safeGetString(classRef, "sectionName", "");
						String cType = translateInstructionalType(safeGetString(classRef, "subpartType", null));

						Element classEl = distPrefEl.addElement("class");
						classEl.addAttribute("subject", subjAbbv);
						if (cCourse != null && !cCourse.isEmpty()) {
							classEl.addAttribute("course", cCourse);
						}
						classEl.addAttribute("suffix", cSection);
						if (cType != null && !cType.isEmpty()) {
							classEl.addAttribute("type", cType);
						}
					}
				}

				if (note != null && !note.isEmpty()) {
					Element noteEl = distPrefEl.addElement("note");
					noteEl.setText(note);
				}
			}
		}

		if (rootJson.has("courses") && rootJson.get("courses").isJsonArray()) {
			for (JsonElement courseElem : rootJson.getAsJsonArray("courses")) {
				if (!courseElem.isJsonObject()) continue;
				JsonObject courseObj = courseElem.getAsJsonObject();
				String courseNbr = safeGetString(courseObj, "courseNumber", "");

				if (!courseObj.has("configurations") || !courseObj.get("configurations").isJsonArray()) continue;
				for (JsonElement configElem : courseObj.getAsJsonArray("configurations")) {
					if (!configElem.isJsonObject()) continue;
					JsonObject configObj = configElem.getAsJsonObject();

					if (!configObj.has("subparts") || !configObj.get("subparts").isJsonArray()) continue;
					for (JsonElement subpartElem : configObj.getAsJsonArray("subparts")) {
						if (!subpartElem.isJsonObject()) continue;
						JsonObject subpartObj = subpartElem.getAsJsonObject();
						String subpartType = translateInstructionalType(safeGetString(subpartObj, "type", "Lecture"));

						if (!subpartObj.has("classes") || !subpartObj.get("classes").isJsonArray()) continue;
						for (JsonElement classElem : subpartObj.getAsJsonArray("classes")) {
							if (!classElem.isJsonObject()) continue;
							JsonObject classObj = classElem.getAsJsonObject();
							String sectionName = safeGetString(classObj, "sectionName", "");

							if (classObj.has("roomPreferences") && classObj.get("roomPreferences").isJsonArray()) {
								Element classPrefEl = null;
								for (JsonElement rpElem : classObj.getAsJsonArray("roomPreferences")) {
									if (!rpElem.isJsonObject()) continue;
									JsonObject rpObj = rpElem.getAsJsonObject();
									String feature = safeGetString(rpObj, "feature", null);
									String roomGroup = safeGetString(rpObj, "roomGroup", null);
									String level = translatePreferenceLevel(safeGetString(rpObj, "level", "R"));

									if ((feature != null && !feature.isEmpty()) || (roomGroup != null && !roomGroup.isEmpty())) {
										if (classPrefEl == null) {
											classPrefEl = prefRoot.addElement("class");
											classPrefEl.addAttribute("subject", subjAbbv);
											classPrefEl.addAttribute("course", courseNbr);
											classPrefEl.addAttribute("type", subpartType);
											classPrefEl.addAttribute("suffix", sectionName);
										}
										if (feature != null && !feature.isEmpty()) {
											Element fpEl = classPrefEl.addElement("featurePref");
											fpEl.addAttribute("feature", feature);
											fpEl.addAttribute("level", level);
										}
										if (roomGroup != null && !roomGroup.isEmpty()) {
											Element gpEl = classPrefEl.addElement("groupPref");
											gpEl.addAttribute("group", roomGroup);
											gpEl.addAttribute("level", level);
										}
									}
								}
							}
						}
					}
				}
			}
		}

		if (deptEl.elements().isEmpty()) {
			prefRoot.remove(deptEl);
		}

		return doc;
	}

	protected boolean hasPreferencesContent(Document prefDoc) {
		if (prefDoc == null || prefDoc.getRootElement() == null) return false;
		return prefRootHasChildren(prefDoc.getRootElement());
	}

	protected boolean prefRootHasChildren(Element root) {
		if (root.elements().size() == 0) return false;
		for (Object obj : root.elements()) {
			Element el = (Element) obj;
			if ("department".equals(el.getName()) && el.elements().size() > 0) return true;
			if ("class".equals(el.getName())) return true;
			if ("subpart".equals(el.getName())) return true;
			if ("instructor".equals(el.getName())) return true;
		}
		return false;
	}

	protected static String translateConstraintType(String type) {
		if (type == null || type.trim().isEmpty()) return "DIFF_TIME";
		String upper = type.trim().toUpperCase();
		switch (upper) {
			case "CANNOT_OVERLAP":
				return "DIFF_TIME";
			case "SAME_INSTRUCTOR":
				return "SAME_INSTR";
			case "DIFF_INSTRUCTOR":
				return "DIFF_INSTR";
			case "BACK_TO_BACK":
				return "BTB";
			case "MEET_TOGETHER":
				return "MEET_WITH";
			case "PRECEDENCE":
				return "PRECEDENCE";
			case "BTB_PRECEDENCE":
			case "BACK_TO_BACK_PRECEDENCE":
			case "BACK_TO_BACK_SEQUENCE":
				return "BTB_PRECEDENCE";
			case "SPREAD_DAYS":
				return "SPREAD";
			case "AT_MOST_2_HOURS_APART":
				return "NHB(2)";
			default:
				return type.trim();
		}
	}

	protected static String translateDistributionStructure(String structure) {
		if (structure == null || structure.trim().isEmpty()) return "AllClasses";
		String clean = structure.trim().replaceAll("[_\\-\\s]+", "").toUpperCase();
		switch (clean) {
			case "ALLCLASSES":
			case "ALL":
				return "AllClasses";
			case "PROGRESSIVE":
				return "Progressive";
			case "GROUPSOFTWO":
			case "GROUPSOF2":
			case "PAIR":
				return "GroupsOfTwo";
			case "GROUPSOFTHREE":
			case "GROUPSOF3":
			case "TRIPLET":
				return "GroupsOfThree";
			case "GROUPSOFFOUR":
			case "GROUPSOF4":
				return "GroupsOfFour";
			case "GROUPSOFFIVE":
			case "GROUPSOF5":
				return "GroupsOfFive";
			case "PAIRWISE":
				return "Pairwise";
			case "ONEOFEACH":
			case "ONEPERGROUP":
				return "OneOfEach";
			default:
				try {
					return DistributionPref.Structure.valueOf(structure.trim()).name();
				} catch (Exception e) {
					return "AllClasses";
				}
		}
	}

	protected static String translatePreferenceLevel(String level) {
		if (level == null || level.trim().isEmpty()) return "R";
		String upper = level.trim().toUpperCase();
		switch (upper) {
			case "REQUIRED":
			case "R":
				return "R";
			case "STRONGLY_PREFERRED":
			case "-2":
				return "-2";
			case "PREFERRED":
			case "-1":
				return "-1";
			case "NEUTRAL":
			case "0":
				return "0";
			case "DISCOURAGED":
			case "1":
				return "1";
			case "STRONGLY_DISCOURAGED":
			case "2":
				return "2";
			case "PROHIBITED":
			case "P":
				return "P";
			default:
				return "R";
		}
	}

	
	protected static String translateInstructionalType(String type) {
		if (type == null || type.trim().isEmpty()) return "Lecture";
		String upper = type.trim().toUpperCase();
		switch (upper) {
			case "KULIAH": return "Lecture";
			case "PRAKTIKUM": return "Laboratory";
			case "RESPONSI": return "Recitation";
			case "TUTORIAL": return "Tutorial";
			case "SEMINAR": return "Seminar";
			default: return type.trim();
		}
	}

	protected static String normalizeDays(String input) {
		if (input == null || input.trim().isEmpty()) return "";
		String s = input.trim();
		// bitmask string (e.g. "1000000")
		if (s.matches("[01]+")) {
			StringBuilder days = new StringBuilder();
			if (s.length() > 0 && s.charAt(0) == '1') days.append("M");
			if (s.length() > 1 && s.charAt(1) == '1') days.append("T");
			if (s.length() > 2 && s.charAt(2) == '1') days.append("W");
			if (s.length() > 3 && s.charAt(3) == '1') days.append("Th");
			if (s.length() > 4 && s.charAt(4) == '1') days.append("F");
			if (s.length() > 5 && s.charAt(5) == '1') days.append("S");
			if (s.length() > 6 && s.charAt(6) == '1') days.append("Su");
			return days.toString();
		}
		// numeric bitmask
		if (s.matches("\\d+")) {
			try {
				int m = Integer.parseInt(s);
				StringBuilder days = new StringBuilder();
				if ((m & 64) != 0) days.append("M");
				if ((m & 32) != 0) days.append("T");
				if ((m & 16) != 0) days.append("W");
				if ((m & 8) != 0) days.append("Th");
				if ((m & 4) != 0) days.append("F");
				if ((m & 2) != 0) days.append("S");
				if ((m & 1) != 0) days.append("Su");
				return days.toString();
			} catch (NumberFormatException e) {
				// ignore
			}
		}
		// English and Indonesian names
		s = s.replaceAll("(?i)Monday", "M");
		s = s.replaceAll("(?i)Tuesday", "T");
		s = s.replaceAll("(?i)Wednesday", "W");
		s = s.replaceAll("(?i)Thursday", "Th");
		s = s.replaceAll("(?i)Friday", "F");
		s = s.replaceAll("(?i)Saturday", "S");
		s = s.replaceAll("(?i)Sunday", "Su");

		s = s.replaceAll("(?i)Senin", "M");
		s = s.replaceAll("(?i)Selasa", "T");
		s = s.replaceAll("(?i)Rabu", "W");
		s = s.replaceAll("(?i)Kamis", "Th");
		s = s.replaceAll("(?i)Jumat", "F");
		s = s.replaceAll("(?i)Sabtu", "S");
		s = s.replaceAll("(?i)Minggu", "Su");

		s = s.replaceAll("[^a-zA-Z]", "");

		boolean hasM = s.contains("M");
		boolean hasTh = s.contains("Th");
		if (hasTh) s = s.replace("Th", "");
		boolean hasT = s.contains("T");
		boolean hasW = s.contains("W");
		boolean hasF = s.contains("F");
		boolean hasSu = s.contains("Su");
		if (hasSu) s = s.replace("Su", "");
		boolean hasS = s.contains("S");

		StringBuilder days = new StringBuilder();
		if (hasM) days.append("M");
		if (hasT) days.append("T");
		if (hasW) days.append("W");
		if (hasTh) days.append("Th");
		if (hasF) days.append("F");
		if (hasS) days.append("S");
		if (hasSu) days.append("Su");
		return days.toString();
	}

	protected static String normalizeTime(String timeStr) {
		if (timeStr == null || timeStr.trim().isEmpty()) return "0000";
		String clean = timeStr.trim();
		if (clean.contains(":")) {
			String[] parts = clean.split(":");
			try {
				int hour = Integer.parseInt(parts[0].trim());
				int min = Integer.parseInt(parts[1].trim());
				return String.format(Locale.US, "%02d%02d", hour, min);
			} catch (NumberFormatException e) {
				return clean.replace(":", "");
			}
		} else if (clean.length() == 4 && clean.matches("\\d{4}")) {
			return clean;
		} else if (clean.matches("\\d{1,2}")) {
			try {
				int hour = Integer.parseInt(clean);
				return String.format(Locale.US, "%02d00", hour);
			} catch (NumberFormatException e) {
				return clean;
			}
		} else if (clean.matches("\\d{3}")) {
			try {
				int val = Integer.parseInt(clean);
				int hour = val / 100;
				int min = val % 100;
				return String.format(Locale.US, "%02d%02d", hour, min);
			} catch (NumberFormatException e) {
				return clean;
			}
		}
		return clean;
	}

	protected static class ParsedName {
		String firstName;
		String middleName;
		String lastName;
		String title;
	}

	protected static ParsedName parseName(String rawName) {
		ParsedName result = new ParsedName();
		if (rawName == null || rawName.trim().isEmpty()) return result;

		String name = rawName.trim();
		String degrees = "";
		if (name.contains(",")) {
			int firstComma = name.indexOf(",");
			degrees = name.substring(firstComma + 1).trim();
			name = name.substring(0, firstComma).trim();
		}

		List<String> prefixTitles = new ArrayList<String>();
		String[] tokens = name.split("\\s+");
		List<String> nameTokens = new ArrayList<String>();
		for (String token : tokens) {
			String lower = token.toLowerCase();
			if (lower.startsWith("prof") || lower.startsWith("dr") || lower.startsWith("ir") || lower.startsWith("drs")) {
				prefixTitles.add(token);
			} else {
				nameTokens.add(token);
			}
		}

		StringBuilder titleBuilder = new StringBuilder();
		for (String p : prefixTitles) {
			if (titleBuilder.length() > 0) titleBuilder.append(" ");
			titleBuilder.append(p);
		}
		if (!degrees.isEmpty()) {
			if (titleBuilder.length() > 0) titleBuilder.append(", ");
			titleBuilder.append(degrees);
		}
		result.title = titleBuilder.length() > 0 ? titleBuilder.toString() : null;

		if (nameTokens.isEmpty()) {
			result.lastName = rawName;
		} else if (nameTokens.size() == 1) {
			result.lastName = nameTokens.get(0);
		} else if (nameTokens.size() == 2) {
			result.firstName = nameTokens.get(0);
			result.lastName = nameTokens.get(1);
		} else {
			result.firstName = nameTokens.get(0);
			result.middleName = nameTokens.get(1);
			StringBuilder last = new StringBuilder();
			for (int i = 2; i < nameTokens.size(); i++) {
				if (last.length() > 0) last.append(" ");
				last.append(nameTokens.get(i));
			}
			result.lastName = last.toString();
		}
		return result;
	}

	protected static class ClassNode {
		JsonObject classObj;
		String subpartType;
		String sectionName;
		String parentSection;

		ClassNode(JsonObject classObj, String subpartType, String sectionName, String parentSection) {
			this.classObj = classObj;
			this.subpartType = subpartType;
			this.sectionName = sectionName;
			this.parentSection = parentSection;
		}
	}

	protected Log createLogListener(final List<LogEntry> logEntries, final AtomicInteger errorCount, final AtomicInteger warnCount) {
		return new Log() {
			private void append(String level, Object message, Throwable t) {
				String msg = message == null ? "null" : message.toString();
				String trace = null;
				if (t != null) {
					StringWriter sw = new StringWriter();
					PrintWriter pw = new PrintWriter(sw);
					t.printStackTrace(pw);
					pw.flush();
					trace = sw.toString();
				}
				logEntries.add(new LogEntry(level, msg, trace, new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(new Date())));
			}

			@Override public void trace(Object message) { append("TRACE", message, null); }
			@Override public void trace(Object message, Throwable t) { append("TRACE", message, t); }
			@Override public boolean isTraceEnabled() { return false; }

			@Override public void debug(Object message) { append("DEBUG", message, null); }
			@Override public void debug(Object message, Throwable t) { append("DEBUG", message, t); }
			@Override public boolean isDebugEnabled() { return false; }

			@Override public void info(Object message) { append("INFO", message, null); }
			@Override public void info(Object message, Throwable t) { append("INFO", message, t); }
			@Override public boolean isInfoEnabled() { return true; }

			@Override
			public void warn(Object message) {
				warnCount.incrementAndGet();
				append("WARN", message, null);
			}
			@Override
			public void warn(Object message, Throwable t) {
				warnCount.incrementAndGet();
				append("WARN", message, t);
			}
			@Override public boolean isWarnEnabled() { return true; }

			@Override
			public void error(Object message) {
				errorCount.incrementAndGet();
				append("ERROR", message, null);
			}
			@Override
			public void error(Object message, Throwable t) {
				errorCount.incrementAndGet();
				append("ERROR", message, t);
			}
			@Override public boolean isErrorEnabled() { return true; }

			@Override
			public void fatal(Object message) {
				errorCount.incrementAndGet();
				append("FATAL", message, null);
			}
			@Override
			public void fatal(Object message, Throwable t) {
				errorCount.incrementAndGet();
				append("FATAL", message, t);
			}
			@Override public boolean isFatalEnabled() { return true; }
		};
	}

	protected IngestResponse buildResponse(JsonObject rootJson, boolean offeringsSuccess, boolean preferencesSuccess, int errorCount, int warnCount, String errorMessage, List<LogEntry> logEntries) {
		IngestResponse resp = new IngestResponse();
		resp.iTimestamp = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(new Date());

		if (errorMessage != null && !offeringsSuccess) {
			resp.iStatus = "FAILED";
			resp.iError = errorMessage;
		} else if (errorCount > 0) {
			resp.iStatus = offeringsSuccess ? "PARTIAL_SUCCESS" : "FAILED";
			if (errorMessage != null) resp.iError = errorMessage;
		} else {
			resp.iStatus = "SUCCESS";
		}

		JsonObject academicSession = rootJson.getAsJsonObject("academicSession");
		resp.iAcademicSession = new AcademicSessionSummary(
			safeGetString(academicSession, "year", "").trim(),
			safeGetString(academicSession, "term", "").trim(),
			safeGetString(academicSession, "campus", "").trim()
		);

		resp.iDepartment = safeGetString(rootJson.getAsJsonObject("department"), "code", "").trim();
		resp.iSubjectArea = safeGetString(rootJson.getAsJsonObject("subjectArea"), "abbreviation", "").trim();

		IngestSummary summary = new IngestSummary();
		resp.iSummary = summary;
		summary.iWarningsCount = warnCount;
		summary.iErrorsCount = errorCount;

		List<CourseImportSummary> importedList = new ArrayList<CourseImportSummary>();
		int totalClassesCount = 0;

		JsonArray courses = rootJson.getAsJsonArray("courses");
		summary.iCoursesCount = courses.size();

		for (JsonElement cElem : courses) {
			if (!cElem.isJsonObject()) continue;
			JsonObject cObj = cElem.getAsJsonObject();

			CourseImportSummary cis = new CourseImportSummary();
			cis.iCourseNumber = safeGetString(cObj, "courseNumber", "");
			cis.iTitle = safeGetString(cObj, "title", "");

			int configsCount = 0;
			int courseClassesCount = 0;
			if (cObj.has("configurations") && cObj.get("configurations").isJsonArray()) {
				JsonArray configs = cObj.getAsJsonArray("configurations");
				configsCount = configs.size();
				for (JsonElement cfgElem : configs) {
					if (!cfgElem.isJsonObject()) continue;
					JsonObject cfgObj = cfgElem.getAsJsonObject();
					if (cfgObj.has("subparts") && cfgObj.get("subparts").isJsonArray()) {
						for (JsonElement spElem : cfgObj.getAsJsonArray("subparts")) {
							if (!spElem.isJsonObject()) continue;
							JsonObject spObj = spElem.getAsJsonObject();
							if (spObj.has("classes") && spObj.get("classes").isJsonArray()) {
								courseClassesCount += spObj.getAsJsonArray("classes").size();
							}
						}
					}
				}
			}
			cis.iConfigurationsCount = configsCount;
			cis.iClassesCount = courseClassesCount;
			totalClassesCount += courseClassesCount;
			importedList.add(cis);
		}

		summary.iClassesCount = totalClassesCount;

		if (rootJson.has("distributionConstraints") && rootJson.get("distributionConstraints").isJsonArray()) {
			summary.iDistributionConstraintsCount = rootJson.getAsJsonArray("distributionConstraints").size();
		} else {
			summary.iDistributionConstraintsCount = 0;
		}

		resp.iCoursesImported = importedList;
		resp.iLogs = logEntries;

		return resp;
	}

	public static class IngestResponse {
		String iStatus;
		String iTimestamp;
		String iError;
		AcademicSessionSummary iAcademicSession;
		String iDepartment;
		String iSubjectArea;
		IngestSummary iSummary;
		List<CourseImportSummary> iCoursesImported;
		List<LogEntry> iLogs;

		public String getStatus() { return iStatus; }
		public String getTimestamp() { return iTimestamp; }
		public String getError() { return iError; }
		public AcademicSessionSummary getAcademicSession() { return iAcademicSession; }
		public String getDepartment() { return iDepartment; }
		public String getSubjectArea() { return iSubjectArea; }
		public IngestSummary getSummary() { return iSummary; }
		public List<CourseImportSummary> getCoursesImported() { return iCoursesImported; }
		public List<LogEntry> getLogs() { return iLogs; }
	}

	public static class AcademicSessionSummary {
		String iYear;
		String iTerm;
		String iCampus;

		public AcademicSessionSummary(String year, String term, String campus) {
			this.iYear = year;
			this.iTerm = term;
			this.iCampus = campus;
		}

		public String getYear() { return iYear; }
		public String getTerm() { return iTerm; }
		public String getCampus() { return iCampus; }
	}

	public static class IngestSummary {
		int iCoursesCount;
		int iClassesCount;
		int iDistributionConstraintsCount;
		int iWarningsCount;
		int iErrorsCount;

		public int getCoursesCount() { return iCoursesCount; }
		public int getClassesCount() { return iClassesCount; }
		public int getDistributionConstraintsCount() { return iDistributionConstraintsCount; }
		public int getWarningsCount() { return iWarningsCount; }
		public int getErrorsCount() { return iErrorsCount; }
	}

	public static class CourseImportSummary {
		String iCourseNumber;
		String iTitle;
		int iConfigurationsCount;
		int iClassesCount;

		public String getCourseNumber() { return iCourseNumber; }
		public String getTitle() { return iTitle; }
		public int getConfigurationsCount() { return iConfigurationsCount; }
		public int getClassesCount() { return iClassesCount; }
	}

	public static class LogEntry {
		String iLevel;
		String iMessage;
		String iStackTrace;
		String iTimestamp;

		public LogEntry(String level, String message, String stackTrace, String timestamp) {
			this.iLevel = level;
			this.iMessage = message;
			this.iStackTrace = stackTrace;
			this.iTimestamp = timestamp;
		}

		public String getLevel() { return iLevel; }
		public String getMessage() { return iMessage; }
		public String getStackTrace() { return iStackTrace; }
		public String getTimestamp() { return iTimestamp; }
	}
}
