import { useState, useEffect } from 'react';

const API_BASE = 'http://localhost:8000';

interface TranscriptLine {
  id: number;
  role: string;
  text: string;
  created_at: string;
  is_partial: boolean;
}

interface Call {
  call_sid: string;
  session_id: string;
  from_number: string;
  to_number: string;
  status: string;
  created_at: string;
  updated_at: string;
  timeline: TranscriptLine[];
}

function App() {
  const [calls, setCalls] = useState<Call[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchCalls = async () => {
    try {
      const response = await fetch(`${API_BASE}/telephony/twilio/calls`);
      if (!response.ok) throw new Error('Failed to fetch calls');
      const data = await response.json();
      setCalls(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCalls();
    const interval = setInterval(fetchCalls, 3000); // Refresh every 3 seconds
    return () => clearInterval(interval);
  }, []);

  const formatTime = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleTimeString();
  };

  const formatDate = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
  };

  const getRoleBadgeColor = (role: string) => {
    switch(role) {
      case 'user': return 'bg-blue-100 text-blue-800';
      case 'assistant': return 'bg-green-100 text-green-800';
      case 'system': return 'bg-gray-100 text-gray-800';
      default: return 'bg-gray-100 text-gray-600';
    }
  };

  const getStatusBadgeColor = (status: string) => {
    switch(status) {
      case 'completed': return 'bg-green-100 text-green-800';
      case 'in-progress': return 'bg-yellow-100 text-yellow-800';
      case 'stream_started': return 'bg-blue-100 text-blue-800';
      case 'stream_stopped': return 'bg-gray-100 text-gray-800';
      default: return 'bg-gray-100 text-gray-600';
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading calls...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">🍕 KitchenCall Dashboard</h1>
              <p className="text-gray-600 mt-1">Phone order management</p>
            </div>
            <div className="text-right">
              <div className="text-sm text-gray-500">Total Calls</div>
              <div className="text-2xl font-bold text-gray-900">{calls.length}</div>
            </div>
          </div>
        </div>
      </header>

      {/* Error Banner */}
      {error && (
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <div className="flex">
              <div className="flex-shrink-0">
                <span className="text-red-600">⚠️</span>
              </div>
              <div className="ml-3">
                <h3 className="text-sm font-medium text-red-800">Error loading calls</h3>
                <p className="text-sm text-red-700 mt-1">{error}</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {calls.length === 0 ? (
          <div className="bg-white rounded-lg shadow-sm p-12 text-center">
            <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
            </svg>
            <h3 className="mt-2 text-sm font-medium text-gray-900">No calls yet</h3>
            <p className="mt-1 text-sm text-gray-500">Phone calls will appear here when they come in.</p>
          </div>
        ) : (
          <div className="space-y-6">
            {calls.map((call) => (
              <div key={call.call_sid} className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
                {/* Call Header */}
                <div className="bg-gradient-to-r from-blue-50 to-blue-100 px-6 py-4 border-b border-gray-200">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-4">
                      <div className="flex-shrink-0">
                        <div className="h-12 w-12 rounded-full bg-blue-600 flex items-center justify-center text-white font-bold">
                          📞
                        </div>
                      </div>
                      <div>
                        <div className="flex items-center space-x-2">
                          <h3 className="text-lg font-semibold text-gray-900">
                            {call.from_number}
                          </h3>
                          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getStatusBadgeColor(call.status)}`}>
                            {call.status}
                          </span>
                        </div>
                        <p className="text-sm text-gray-600 mt-1">
                          Call SID: {call.call_sid.substring(0, 20)}...
                        </p>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-sm text-gray-500">Called</div>
                      <div className="text-sm font-medium text-gray-900">{formatDate(call.created_at)}</div>
                    </div>
                  </div>
                </div>

                {/* Transcript */}
                <div className="px-6 py-4">
                  <h4 className="text-sm font-medium text-gray-700 mb-3">Conversation Timeline</h4>
                  {call.timeline.length === 0 ? (
                    <p className="text-sm text-gray-500 italic">No transcript yet...</p>
                  ) : (
                    <div className="space-y-3">
                      {call.timeline.map((line) => (
                        <div key={line.id} className="flex items-start space-x-3">
                          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getRoleBadgeColor(line.role)}`}>
                            {line.role}
                          </span>
                          <div className="flex-1">
                            <p className={`text-sm text-gray-900 ${line.is_partial ? 'italic text-gray-600' : ''}`}>
                              {line.text}
                            </p>
                            <p className="text-xs text-gray-500 mt-1">{formatTime(line.created_at)}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 text-center text-sm text-gray-500">
        <p>Auto-refreshing every 3 seconds</p>
      </footer>
    </div>
  );
}

export default App;
