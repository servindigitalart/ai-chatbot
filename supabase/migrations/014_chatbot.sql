-- Chatbot configuration per clinic
-- One config per clinic (can have multiple widgets pointing to same config)
CREATE TABLE chatbot_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id UUID REFERENCES clinics(id) ON DELETE CASCADE,

    -- Identity
    bot_name TEXT DEFAULT 'Assistant',      -- e.g. "Maya" or "Austin Derm Assistant"
    welcome_message TEXT NOT NULL,
    fallback_message TEXT DEFAULT 'I''ll connect you with our team shortly.',

    -- Behavior
    tone TEXT DEFAULT 'friendly'
        CHECK (tone IN ('professional', 'friendly', 'warm', 'concise')),
    language TEXT DEFAULT 'en',

    -- System prompt (AI-generated, admin can edit)
    system_prompt TEXT NOT NULL,

    -- Lead capture config
    capture_name BOOLEAN DEFAULT true,
    capture_email BOOLEAN DEFAULT true,
    capture_phone BOOLEAN DEFAULT true,
    capture_service_interest BOOLEAN DEFAULT true,
    require_email_before_chat BOOLEAN DEFAULT false,

    -- Qualification questions (ordered list)
    qualification_questions JSONB DEFAULT '[]',
    -- e.g. [{"question": "What brings you in today?", "type": "service_select"},
    --        {"question": "Have you visited us before?", "type": "yes_no"}]

    -- Services the clinic offers (for chatbot context)
    services JSONB DEFAULT '[]',
    -- e.g. ["Botox", "Acne Treatment", "Chemical Peels"]

    -- FAQs (AI-generated + admin editable)
    faqs JSONB DEFAULT '[]',
    -- e.g. [{"question": "Do you accept insurance?", "answer": "Yes, we accept..."}]

    -- Widget appearance
    primary_color TEXT DEFAULT '#007AE6',
    widget_position TEXT DEFAULT 'bottom-right'
        CHECK (widget_position IN ('bottom-right', 'bottom-left')),
    widget_avatar_url TEXT,              -- clinic logo or avatar for bot

    -- Scheduling integration
    scheduling_enabled BOOLEAN DEFAULT false,
    scheduling_url TEXT,                 -- Calendly, ZocDoc, or custom URL
    scheduling_button_text TEXT DEFAULT 'Book Appointment',

    -- Email marketing integration
    auto_enroll_leads BOOLEAN DEFAULT true,
    email_sequence_trigger TEXT DEFAULT 'new_chatbot_lead',

    -- Status
    is_active BOOLEAN DEFAULT false,     -- must be activated by admin
    is_ai_generated BOOLEAN DEFAULT true,
    ai_generation_context JSONB,         -- what data was used to generate config

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(clinic_id)                    -- one config per clinic
);

-- Chat sessions (one per visitor conversation)
CREATE TABLE chatbot_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id UUID REFERENCES clinics(id) ON DELETE CASCADE,
    config_id UUID REFERENCES chatbot_configs(id),

    -- Visitor identity (populated during conversation)
    visitor_id TEXT,                     -- anonymous browser fingerprint
    contact_name TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    service_interest TEXT,               -- what service they want

    -- Session metadata
    source_url TEXT,                     -- page where chat was started
    source_surface TEXT DEFAULT 'widget'
        CHECK (source_surface IN ('widget', 'portal', 'preview')),

    -- Qualification
    is_qualified BOOLEAN DEFAULT false,
    qualification_score INTEGER DEFAULT 0, -- 0-100
    qualification_data JSONB DEFAULT '{}', -- answers to qualification questions

    -- Lead capture
    lead_captured BOOLEAN DEFAULT false,
    lead_id UUID,                        -- references email_contacts after capture
    enrolled_in_sequence BOOLEAN DEFAULT false,

    -- Session state
    status TEXT DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'abandoned')),
    message_count INTEGER DEFAULT 0,

    started_at TIMESTAMPTZ DEFAULT NOW(),
    last_message_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- Individual messages in a session
CREATE TABLE chatbot_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES chatbot_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,

    -- Metadata
    intent TEXT,                         -- detected intent: faq, lead_capture, scheduling, general
    confidence DECIMAL(4,3),             -- 0-1 confidence of intent detection

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- FAQs library per clinic (normalized for easier editing)
CREATE TABLE chatbot_faqs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id UUID REFERENCES clinics(id) ON DELETE CASCADE,
    config_id UUID REFERENCES chatbot_configs(id),
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category TEXT,                       -- "pricing", "services", "location", "insurance"
    is_active BOOLEAN DEFAULT true,
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Captured leads (summary view — full data in email_contacts)
CREATE TABLE chatbot_leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id UUID REFERENCES clinics(id) ON DELETE CASCADE,
    session_id UUID REFERENCES chatbot_sessions(id),

    name TEXT,
    email TEXT,
    phone TEXT,
    service_interest TEXT,
    notes TEXT,                          -- summary of what they discussed

    -- Lead quality
    qualification_score INTEGER DEFAULT 0,
    is_hot BOOLEAN DEFAULT false,        -- score >= 70

    -- Status tracking
    status TEXT DEFAULT 'new'
        CHECK (status IN ('new', 'contacted', 'converted', 'lost')),

    -- Integration
    email_contact_id TEXT,               -- ID in email-marketing service
    enrolled_in_sequence BOOLEAN DEFAULT false,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_chatbot_sessions_clinic ON chatbot_sessions(clinic_id, started_at DESC);
CREATE INDEX idx_chatbot_sessions_status ON chatbot_sessions(status, clinic_id);
CREATE INDEX idx_chatbot_messages_session ON chatbot_messages(session_id, created_at ASC);
CREATE INDEX idx_chatbot_leads_clinic ON chatbot_leads(clinic_id, created_at DESC);
CREATE INDEX idx_chatbot_leads_status ON chatbot_leads(clinic_id, status);
CREATE INDEX idx_chatbot_faqs_clinic ON chatbot_faqs(clinic_id, is_active);
CREATE INDEX idx_chatbot_configs_clinic ON chatbot_configs(clinic_id);

-- Apply at:
-- https://supabase.com/dashboard/project/xoodzawfzfhhjaavthjn/sql/new
-- Verify: SELECT table_name FROM information_schema.tables
--         WHERE table_schema='public' AND table_name LIKE 'chatbot_%'
--         ORDER BY table_name;
-- Expected: chatbot_configs, chatbot_faqs, chatbot_leads,
--           chatbot_messages, chatbot_sessions (5 tables)
