(function(global){
  "use strict";
  const DebriPod = global.DebriPod = global.DebriPod || {};

  function emptyFilters(){ return {sources:new Set(), types:new Set(), indexers:new Set(), media:new Set()}; }
  function createState(){
    return {q:"", searchId:"", allResults:[], resultById:new Map(), visibleIds:[], filters:emptyFilters(), availableFilters:{sources:[],types:[],indexers:[],media:[]}, providerStatus:[], running:false, filter:"", cached:false, editField:"", editValue:""};
  }
  function values(result, key){
    const raw = result && result.filter_values && result.filter_values[key];
    return Array.isArray(raw) ? raw.map(String) : [];
  }
  function compact(result){
    return {id:String(result.result_id || ""), search_blob:String(result.search_blob || "").toLowerCase(), sources:values(result,"sources"), types:values(result,"types"), indexers:values(result,"indexers"), media:values(result,"media"), rank_score:Number(result.rank_score || 0)};
  }
  function pill(text, filterKind){ return {text:String(text), filter_kind:filterKind || "", filter_value:String(text)}; }

  class SearchResultsModel {
    constructor(target, options){
      this.state = target || createState();
      const defaults = createState();
      Object.keys(defaults).forEach(key=>{ if(this.state[key] == null) this.state[key] = defaults[key]; });
      if(!(this.state.resultById instanceof Map)) this.state.resultById = new Map();
      Object.keys(this.state.filters || {}).forEach(key=>{ if(!(this.state.filters[key] instanceof Set)) this.state.filters[key] = new Set(this.state.filters[key] || []); });
      this.options = options || {};
      this.worker = null; this.timer = 0; this.requestId = 0; this._freeFilterText = "";
      this._startWorker();
    }
    _startWorker(){
      if(this.options.disableWorker || typeof global.Worker !== "function") return;
      try{
        const version = encodeURIComponent(String(global.DEBRIPOD_ASSET_VERSION || ""));
        this.worker = new Worker("/static/js/search-results-worker.js?v=" + version);
        this.worker.onmessage = event=>{ if(event.data && event.data.type === "result") this._applyIds(event.data.ids || []); };
      }catch(_error){ this.worker = null; }
    }
    reset(query, searchId){
      this.state.q = String(query || ""); this.state.searchId = String(searchId || "");
      this.state.allResults = []; this.state.resultById = new Map(); this.state.visibleIds = [];
      this.state.availableFilters = {sources:[],types:[],indexers:[],media:[]}; this.state.providerStatus = []; this.state.running = true;
      this._syncWorker();
    }
    _ingest(results){
      for(const raw of (results || [])){
        if(!raw || !raw.result_id) continue;
        const id = String(raw.result_id), existing = this.state.resultById.get(id);
        this.state.resultById.set(id, existing ? Object.assign({}, existing, raw) : raw);
      }
      this.state.allResults = Array.from(this.state.resultById.values()).sort((a,b)=>Number(b.rank_score||0)-Number(a.rank_score||0)||String(a.result_id).localeCompare(String(b.result_id)));
      this.state.results = this.state.allResults;
      this.state.last_count = this.state.allResults.length;
      this._collectFilters(); this._parseFilterText(this.state.filter || ""); this._syncWorker();
    }
    ingestSource(event){
      const group = String(event.provider_group || "");
      const row = {provider_group:group, source_status:event.source_status || {}, error:String(event.error || ""), duration_ms:Number(event.duration_ms || 0), result_count:Number(event.result_count || (event.results || []).length), done:true};
      const index = this.state.providerStatus.findIndex(item=>item.provider_group === group);
      if(index >= 0) this.state.providerStatus[index] = row; else this.state.providerStatus.push(row);
      this._ingest(event.results || []);
    }
    ingestFinal(event){
      this._ingest(event.results || []); this.state.providerStatus = Array.isArray(event.provider_status) ? event.provider_status.slice() : this.state.providerStatus;
      this.state.running = false; this.state.cached = !!event.cached;
      this.state.searching = false;
    }
    ingestEvent(event){ if(event && event.event === "source") this.ingestSource(event); else if(event && event.event === "done") this.ingestFinal(event); }
    _collectFilters(){
      const found = {sources:new Set(),types:new Set(),indexers:new Set(),media:new Set()};
      this.state.allResults.forEach(result=>Object.keys(found).forEach(key=>values(result,key).forEach(value=>found[key].add(value))));
      this.state.availableFilters = Object.fromEntries(Object.keys(found).map(key=>[key,Array.from(found[key]).sort()]));
    }
    _message(){ return {filters:Object.fromEntries(Object.keys(this.state.filters).map(key=>[key,Array.from(this.state.filters[key])])), text:String(this._freeFilterText || "")}; }
    _parseFilterText(text){
      this.state.filter=String(text||"");
      Object.values(this.state.filters).forEach(set=>set.clear());
      const aliases={source:"sources",src:"sources",type:"types",kind:"types",indexer:"indexers",tracker:"indexers",media:"media"};
      const free=[];
      const parts=this.state.filter.match(/(?:[^\s"]+|"[^"]*")+/g)||[];
      parts.forEach(token=>{
        const match=String(token).match(/^([a-z]+):(.*)$/i);
        const kind=match&&aliases[String(match[1]).toLowerCase()];
        if(!kind){ free.push(token.replace(/^"|"$/g,"")); return; }
        const requested=String(match[2]||"").replace(/^"|"$/g,"");
        const available=(this.state.availableFilters&&this.state.availableFilters[kind])||[];
        const actual=available.find(value=>String(value).toLowerCase()===requested.toLowerCase());
        if(actual!=null) this.state.filters[kind].add(String(actual)); else free.push(token);
      });
      this._freeFilterText=free.join(" ");
    }
    _serializeFilterText(){
      const names={sources:"source",types:"type",indexers:"indexer",media:"media"}, parts=[];
      Object.keys(names).forEach(kind=>Array.from(this.state.filters[kind]).forEach(value=>parts.push(names[kind]+":"+(/\s/.test(value)?'"'+value+'"':value))));
      if(this._freeFilterText) parts.push(this._freeFilterText);
      this.state.filter=parts.join(" ");
    }
    _syncWorker(){
      const records = this.state.allResults.map(compact), message = Object.assign({type:"init",records:records,requestId:String(++this.requestId)}, this._message());
      if(this.worker){ this.worker.postMessage(message); return; }
      this._filterFallback(records, message);
    }
    _filterFallback(records, message){
      const helper = global.DebriPodSearchWorker && global.DebriPodSearchWorker.filterRecords;
      if(helper){ this._applyIds(helper(records, message)); return; }
      const ids = []; let index = 0;
      const selected = message.filters, text = String(message.text || "").toLowerCase();
      const process = ()=>{
        const end = Math.min(records.length, index + 1000);
        for(;index<end;index++){
          const record=records[index];
          const ok=Object.keys(selected).every(key=>!selected[key].length || (record[key]||[]).some(value=>selected[key].includes(String(value)))) && (!text || record.search_blob.includes(text));
          if(ok) ids.push(record.id);
        }
        if(index<records.length) setTimeout(process,0); else this._applyIds(ids);
      };
      process();
    }
    applyFilters(text){
      if(text != null) this._parseFilterText(text);
      clearTimeout(this.timer); this.timer = setTimeout(()=>{
        const message=Object.assign({type:"filter",requestId:String(++this.requestId)},this._message());
        if(this.worker) this.worker.postMessage(message); else this._filterFallback(this.state.allResults.map(compact),message);
      },120);
    }
    toggleFilter(kind, value){ const set=this.state.filters[kind]; if(!set)return; set.has(value)?set.delete(value):set.add(value); this._serializeFilterText(); this.applyFilters(); }
    clearFilters(){ Object.values(this.state.filters).forEach(set=>set.clear()); this._freeFilterText=""; this.state.filter=""; this.applyFilters(); }
    _applyIds(ids){ this.state.visibleIds = ids.slice(); if(typeof this.options.onChange === "function") this.options.onChange(ids); }
    resultRows(){ return this.state.visibleIds.map(id=>this.resultById(id)).filter(Boolean).map(result=>this.toRow(result)); }
    resultById(id){ return this.state.resultById.get(String(id)); }
    toRow(result){
      const pills=[]; const data=result.provider_data||{};
      pills.push(pill(result.source_label || result.source,"sources"));
      if(result.source === "torrent") (data.indexer_labels || []).forEach(label=>pills.push(pill(label,"indexers")));
      pills.push(pill(result.kind_label || result.kind,"types"));
      if(result.source === "torrent" && data.category) pills.push(pill(data.category,"media"));
      return {kind:"libsearch_result",row_layout_key:"search-result-fixed",label:String(result.title||"Result"),sub_label:String(result.subtitle||result.artist||result.album||""),source:String(result.source||""),result_id:String(result.result_id||""),raw:result,pills:pills};
    }
  }
  DebriPod.SearchResultsModel = SearchResultsModel;
  DebriPod.createSearchResultsState = createState;
  if(typeof module !== "undefined" && module.exports) module.exports={SearchResultsModel:SearchResultsModel,createState:createState};
})(typeof window !== "undefined" ? window : globalThis);
