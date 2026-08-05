"""
Vostud AI - Model Switcher with Custom Model Tiers
"""

class ModelSwitcher:
    """Manage and switch between different AI models with Vostud branding"""
    
    # Vostud model tier mapping
    VOSTUD_MODELS = {
        # Pro tier - Best quality
        'vostud-2.5-pro': {
            'api': 'groq',
            'model': 'llama-3.3-70b-versatile',
            'tier': 'pro',
            'speed': 'medium',
            'quality': 'highest',
            'cost': 'free',
            'description': 'Highest quality model for complex reasoning'
        },
        'vostud-2.5-flash': {
            'api': 'groq',
            'model': 'llama-3.1-8b-instant',
            'tier': 'flash',
            'speed': 'fast',
            'quality': 'high',
            'cost': 'free',
            'description': 'Fast model with good quality'
        },
        'vostud-2.0-pro': {
            'api': 'gemini',
            'model': 'gemini-2.5-pro',
            'tier': 'pro',
            'speed': 'medium',
            'quality': 'high',
            'cost': 'free',
            'description': 'Google Gemini Pro for research'
        },
        'vostud-2.0-flash': {
            'api': 'gemini',
            'model': 'gemini-2.0-flash',
            'tier': 'flash',
            'speed': 'fast',
            'quality': 'good',
            'cost': 'free',
            'description': 'Google Gemini Flash for speed'
        },
        'vostud-1.5-pro': {
            'api': 'openrouter',
            'model': 'qwen/qwen-2.5-7b-instruct',
            'tier': 'pro',
            'speed': 'medium',
            'quality': 'high',
            'cost': 'free',
            'description': 'Qwen 2.5 for quality responses'
        },
        'vostud-1.5-flash': {
            'api': 'openrouter',
            'model': 'meta-llama/llama-3.2-3b-instruct',
            'tier': 'flash',
            'speed': 'fast',
            'quality': 'good',
            'cost': 'free',
            'description': 'Llama 3.2 for fast responses'
        },
        'vostud-pro': {
            'api': 'openai',
            'model': 'gpt-4',
            'tier': 'pro',
            'speed': 'medium',
            'quality': 'highest',
            'cost': 'paid',
            'description': 'OpenAI GPT-4 - Best quality (paid)'
        },
        'vostud-flash': {
            'api': 'openai',
            'model': 'gpt-3.5-turbo',
            'tier': 'flash',
            'speed': 'fast',
            'quality': 'good',
            'cost': 'paid',
            'description': 'OpenAI GPT-3.5 - Fast responses (paid)'
        },
        'vostud-local': {
            'api': 'ollama',
            'model': 'llama2:latest',
            'tier': 'local',
            'speed': 'slow',
            'quality': 'good',
            'cost': 'free',
            'description': 'Local Ollama - Private, free (slower)'
        }
    }
    
    def __init__(self, engine):
        self.engine = engine
        self.current_model = None
        self.available_models = self._get_available_models()
        self.model_performance = {}
        self.model_status = {}
        self.auto_mode = True
        self.fallback_chain = []
        self.vostud_models = self.VOSTUD_MODELS
    
    def _get_available_models(self):
        """Get all available models including Vostud branded ones"""
        models = {}
        
        # Add Vostud branded models
        for name, config in self.VOSTUD_MODELS.items():
            # Check if the underlying API is available
            api_name = config['api']
            if api_name in self.engine.apis:
                models[name] = {
                    'key': name,
                    'api': api_name,
                    'model': config['model'],
                    'type': 'vostud',
                    'tier': config['tier'],
                    'speed': config['speed'],
                    'quality': config['quality'],
                    'cost': config['cost'],
                    'description': config['description'],
                    'status': 'untested'
                }
        
        # Also add raw API models
        for api_name, api_config in self.engine.apis.items():
            for model in api_config['models']:
                key = f"{api_name}/{model}"
                if key not in models:
                    models[key] = {
                        'key': key,
                        'api': api_name,
                        'model': model,
                        'type': 'raw',
                        'tier': 'raw',
                        'speed': 'unknown',
                        'quality': 'unknown',
                        'cost': 'unknown',
                        'description': f'Raw {api_name} model',
                        'status': 'untested'
                    }
        
        return models
    
    def get_vostud_model(self, model_name: str) -> dict:
        """Get the underlying API and model for a Vostud model name"""
        if model_name in self.VOSTUD_MODELS:
            return self.VOSTUD_MODELS[model_name]
        return None
    
    def get_best_model(self, task_type='general', tier='auto'):
        """Auto-select the best model based on task and tier"""
        
        # If auto mode is off and current model is set
        if not self.auto_mode and self.current_model:
            return self.current_model
        
        # Determine tier preference
        tier_preference = ['flash', 'pro', 'local']
        if tier == 'pro':
            tier_preference = ['pro', 'flash', 'local']
        elif tier == 'flash':
            tier_preference = ['flash', 'pro', 'local']
        elif tier == 'local':
            tier_preference = ['local', 'flash', 'pro']
        
        # Score models
        scored_models = []
        for key, info in self.available_models.items():
            if info.get('status') == 'failed':
                continue
            
            score = 0
            
            # Prefer Vostud branded models
            if info['type'] == 'vostud':
                score += 10
            
            # Tier preference
            if info['tier'] in tier_preference:
                score += 10 - tier_preference.index(info['tier'])
            
            # Cost
            if info['cost'] == 'free':
                score += 5
            
            # Speed
            if info['speed'] == 'fast':
                score += 3
            elif info['speed'] == 'medium':
                score += 1
            
            # Working status
            if info['status'] == 'working':
                score += 5
            
            scored_models.append((score, key))
        
        # Sort by score (highest first)
        scored_models.sort(reverse=True)
        
        if scored_models:
            return scored_models[0][1]
        
        # Fallback to first available
        if self.available_models:
            return list(self.available_models.keys())[0]
        
        return None
    
    def get_model_info(self, model_key: str) -> dict:
        """Get detailed info about a specific model"""
        if model_key in self.available_models:
            return self.available_models[model_key]
        return None
    
    def list_vostud_models(self) -> list:
        """List only Vostud branded models"""
        return [
            {
                'key': k,
                'description': v['description'],
                'tier': v['tier'],
                'speed': v['speed'],
                'quality': v['quality'],
                'cost': v['cost'],
                'status': self.available_models.get(k, {}).get('status', 'untested')
            }
            for k, v in self.VOSTUD_MODELS.items()
            if k in self.available_models
        ]
    
    def get_available_models_list(self) -> list:
        """Get list of all available models with status"""
        result = []
        for key, info in self.available_models.items():
            status = info.get('status', 'unknown')
            speed = info.get('speed', 'unknown')
            result.append({
                'key': key,
                'api': info.get('api', 'unknown'),
                'model': info.get('model', key),
                'type': info.get('type', 'raw'),
                'status': status,
                'speed': speed,
                'tier': info.get('tier', 'unknown'),
                'cost': info.get('cost', 'unknown'),
                'description': info.get('description', '')
            })
        return result
    
    def get_current_model(self) -> str:
        """Get the currently selected model"""
        if self.auto_mode:
            return "auto"
        return self.current_model or "auto"
    
    def set_model(self, model_key: str) -> str:
        """Set a specific model"""
        if model_key == 'auto':
            self.auto_mode = True
            return "Switched to auto mode"
        
        if model_key in self.available_models:
            self.current_model = model_key
            self.auto_mode = False
            return f"Switched to model: {model_key}"
        
        # Check if it's a Vostud model name
        if model_key in self.VOSTUD_MODELS:
            self.current_model = model_key
            self.auto_mode = False
            return f"Switched to Vostud model: {model_key}"
        
        return f"Model '{model_key}' not found"
    
    def set_auto_mode(self, enabled: bool) -> str:
        """Enable or disable auto mode"""
        self.auto_mode = enabled
        if enabled:
            return "Auto mode enabled"
        return "Auto mode disabled"
    
    def switch_to_next_model(self) -> str:
        """Switch to the next available model"""
        if not self.available_models:
            return "No models available"
        
        keys = list(self.available_models.keys())
        if self.current_model in keys:
            idx = keys.index(self.current_model)
            next_idx = (idx + 1) % len(keys)
            self.current_model = keys[next_idx]
            self.auto_mode = False
            return f"Switched to: {self.current_model}"
        else:
            self.current_model = keys[0]
            self.auto_mode = False
            return f"Switched to: {self.current_model}"
    
    def mark_model_status(self, model_key: str, status: str, speed: str = None) -> None:
        """Mark a model's status for tracking"""
        if model_key in self.available_models:
            self.available_models[model_key]['status'] = status
            if speed:
                self.available_models[model_key]['speed'] = speed
