# Vostud AI - Model Switcher System
# Allows manual and automatic model switching

class ModelSwitcher:
    """Manage and switch between different AI models"""
    
    def __init__(self, engine):
        self.engine = engine
        self.current_model = None
        self.available_models = self._get_available_models()
        self.model_performance = {}
        self.model_status = {}
        self.auto_mode = True
        self.fallback_chain = []
    
    def _get_available_models(self):
        """Get all available models across all APIs"""
        models = {}
        
        for api_name, api_config in self.engine.apis.items():
            for model in api_config['models']:
                models[f"{api_name}/{model}"] = {
                    'api': api_name,
                    'model': model,
                    'type': api_config['type'],
                    'status': 'untested',
                    'speed': None,
                    'accuracy': None,
                    'cost': self._get_model_cost(api_name, model)
                }
        
        return models
    
    def _get_model_cost(self, api, model):
        """Get cost tier for model"""
        cost_map = {
            'groq': {'free': True, 'tier': 'free'},
            'openrouter': {'free': True, 'tier': 'free' if ':free' in model else 'paid'},
            'gemini': {'free': True, 'tier': 'free'},
            'ollama': {'free': True, 'tier': 'local'},
            'openai': {'free': False, 'tier': 'paid'}
        }
        return cost_map.get(api, {'free': True, 'tier': 'unknown'})
    
    def set_auto_mode(self, enabled=True):
        """Enable or disable automatic model selection"""
        self.auto_mode = enabled
        return f"Auto mode {'enabled' if enabled else 'disabled'}"
    
    def set_model(self, model_key):
        """Manually set a specific model"""
        if model_key in self.available_models:
            self.current_model = model_key
            self.auto_mode = False
            return f"Switched to model: {model_key}"
        elif model_key == 'auto':
            self.auto_mode = True
            return "Switched to automatic model selection"
        else:
            return f"Model '{model_key}' not found. Available models: {list(self.available_models.keys())[:10]}..."
    
    def get_current_model(self):
        """Get the currently active model"""
        if self.auto_mode:
            return "auto (automatic selection)"
        return self.current_model or "auto (default)"
    
    def get_available_models_list(self):
        """Get list of all available models with status"""
        result = []
        for key, info in self.available_models.items():
            status = info.get('status', 'unknown')
            speed = info.get('speed', 'unknown')
            result.append({
                'key': key,
                'api': info['api'],
                'model': info['model'],
                'status': status,
                'speed': speed,
                'cost': info['cost']
            })
        return result
    
    def get_best_model(self, task_type='general'):
        """Auto-select the best model for a task"""
        if not self.auto_mode and self.current_model:
            return self.current_model
        
        # Priority order: speed and availability
        model_priority = []
        
        # Try working models first
        for key, info in self.available_models.items():
            if info.get('status') == 'working':
                # Score based on speed and cost
                score = 0
                if info['cost']['free']:
                    score += 10
                if info['api'] == 'groq':
                    score += 5  # Groq is fastest
                if 'flash' in info['model']:
                    score += 3  # Flash models are fast
                if 'instant' in info['model']:
                    score += 3
                model_priority.append((score, key))
        
        # Sort by score (highest first)
        model_priority.sort(reverse=True)
        
        if model_priority:
            return model_priority[0][1]
        
        # If no working models, try any model
        if self.available_models:
            return list(self.available_models.keys())[0]
        
        return None
    
    def mark_model_status(self, model_key, status, speed=None):
        """Mark a model's status for tracking"""
        if model_key in self.available_models:
            self.available_models[model_key]['status'] = status
            if speed:
                self.available_models[model_key]['speed'] = speed
    
    def get_model_info(self, model_key):
        """Get detailed info about a specific model"""
        if model_key in self.available_models:
            return self.available_models[model_key]
        return None
    
    def switch_to_next_model(self):
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
            return f"Switched to: {self.current_model}"